"""Integrate fact authority, matching, materials and the local CRM."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from .store import PROJECT_ROOT, StateError, Store, canonical_json


class Workflow:
    def __init__(self, store: Store, candidate_path: str | Path | None = None):
        self.store = store
        self.candidate_path = candidate_path

    def candidate(self) -> dict:
        from .candidate import load_candidate
        return load_candidate(self.candidate_path)

    def assess(self, opportunity_id: int) -> dict:
        from .matching import assess
        candidate = self.candidate()
        job = self.store.get_opportunity(opportunity_id)
        observation = dict(job["observation"]) | {"id": opportunity_id}
        result = assess(observation, candidate)
        assessment_id = self.store.save_assessment(opportunity_id, candidate["candidate_hash"], result)
        return {"opportunity_id": opportunity_id, "assessment_id": assessment_id, "candidate_hash": candidate["candidate_hash"], "assessment": result}

    def prepare(self, opportunity_id: int, *, output_root: str | Path | None = None) -> dict:
        from .materials import build_packet
        candidate = self.candidate()
        job = self.store.get_opportunity(opportunity_id)
        current = next((s for s in job["assessments"] if s["revision_id"] == job["current_revision_id"] and s["candidate_hash"] == candidate["candidate_hash"]), None)
        if current is None:
            result = self.assess(opportunity_id)
            current = next(s for s in self.store.get_opportunity(opportunity_id)["assessments"] if s["id"] == result["assessment_id"])
        # Idempotent preparation reuses immutable files for exactly the same inputs.
        previous = next((p for p in job["packets"] if p["assessment_id"] == current["id"] and p["candidate_hash"] == candidate["candidate_hash"] and p["revision_id"] == job["current_revision_id"]), None)
        if previous:
            self.verify_artifacts(previous)
            return previous
        root = Path(output_root or PROJECT_ROOT / "private" / "packets").resolve()
        folder = root / f"opportunity-{opportunity_id}-r{job['current_revision_id']}-{uuid.uuid4().hex[:12]}"
        folder.mkdir(parents=True, exist_ok=False)
        payload = build_packet(dict(job["observation"]) | {"id": opportunity_id}, candidate, current["payload"], output_dir=folder)
        artifacts = self.collect_artifacts(payload, folder)
        packet_id = self.store.save_packet(opportunity_id, current["id"], candidate["candidate_hash"], payload, artifacts)
        packet = self.store.get_packet(packet_id)
        from .review import render_review
        review_path = render_review(self.store.get_opportunity(opportunity_id), packet, folder / "review.html")
        # The review page is a generated read-only view, outside immutable material files.
        packet["review_path"] = str(review_path)
        return packet

    @staticmethod
    def collect_artifacts(payload: dict, folder: Path) -> dict:
        artifacts = {}
        files = dict(payload.get("files", {}))
        if payload.get("manifest_path"):
            files["manifest"] = payload["manifest_path"]
        for label, value in files.items():
            if not value:
                continue
            if isinstance(value, dict):
                value = value.get("path")
            if not value:
                continue
            path = Path(value)
            if not path.is_absolute():
                path = folder / path
            path = path.resolve()
            if not path.is_relative_to(folder.resolve()):
                raise StateError(f"材料文件越出当前不可变包目录：{label}")
            if not path.is_file():
                raise StateError(f"材料文件不存在：{label}")
            artifacts[label] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}
        if not artifacts:
            raise StateError("材料生成器未返回files，不能保存空材料包")
        return artifacts

    @staticmethod
    def verify_artifacts(packet: dict) -> None:
        for label, artifact in packet["artifacts"].items():
            path = Path(artifact["path"])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise StateError(f"已保存材料被更改：{label}；保留原包并明确重新生成新版本")

    def human_decision(self, opportunity_id: int, decision: str, *, actor: str, note: str = "") -> int:
        return self.store.human_decision(opportunity_id, self.candidate()["candidate_hash"], decision, actor=actor, note=note)

    def approve(self, packet_id: int, *, actor: str, expected_digest: str, note: str = "", accept_unknowns: bool = False, review_note: str = "") -> int:
        packet = self.store.get_packet(packet_id)
        if expected_digest != packet["packet_digest"]:
            raise StateError("人工批准提供的digest与材料包不一致")
        return self.store.approve(packet_id, self.candidate()["candidate_hash"], actor=actor, note=note, accept_unknowns=accept_unknowns, review_note=review_note)

    def mark_applied(self, packet_id: int, *, confirmation_type: str, evidence: str, sent_at: str | None = None) -> int:
        return self.store.mark_applied(packet_id, self.candidate()["candidate_hash"], confirmation_type=confirmation_type, evidence=evidence, sent_at=sent_at)
