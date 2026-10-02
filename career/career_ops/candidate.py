"""Read the controller-reviewed fact ledger; never infer new candidate facts."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, configured_path

WORKSPACE_ROOT = configured_path("workspace_root", PROJECT_ROOT.parent, "CAREER_WORKSPACE_ROOT")
DEFAULT_PROFILE = configured_path("candidate_profile", "../self/career-profile.json", "CAREER_OPS_CANDIDATE")
STATUSES = {"direct", "partial", "unknown", "not_met"}


class CandidateError(ValueError):
    """The reviewed profile or its evidence changed or is malformed."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode("utf-8"))


def resolve_evidence_path(value: str | Path, profile_path: Path | None = None) -> Path:
    """Resolve only workspace-local evidence, including context-resume relative paths."""
    value = Path(value)
    options = [value] if value.is_absolute() else [WORKSPACE_ROOT / value]
    if not value.is_absolute() and profile_path:
        options += [profile_path.parent / value, profile_path.parent.parent / value]
    if not value.is_absolute():
        options += [PROJECT_ROOT / value, PROJECT_ROOT.parent / value]
    for option in options:
        path = option.resolve()
        if not path.is_relative_to(WORKSPACE_ROOT.resolve()):
            raise CandidateError(f"证据路径超出工作区：{value}")
        if path.is_file():
            return path
    raise CandidateError(f"证据文件不存在：{value}")


def _check_source(source: dict, profile_path: Path | None) -> dict:
    if not isinstance(source, dict) or not source.get("path"):
        raise CandidateError("每项事实必须有本地 source.path")
    expected = source.get("sha256", "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise CandidateError(f"证据 SHA256 无效：{source.get('path')}")
    path = resolve_evidence_path(source["path"], profile_path)
    actual = sha256_bytes(path.read_bytes())
    if actual != expected:
        raise CandidateError(f"证据已变化，请重新审核：{source['path']}")
    if not source.get("locator"):
        raise CandidateError(f"事实缺少 source.locator：{source['path']}")
    return {**source, "sha256": actual, "resolved_path": str(path)}


def validate_candidate(profile: dict, *, profile_path: Path | None = None,
                       verify_sources: bool = True) -> dict:
    """Validate the *reviewed* schema; keyword lists are not a fact source."""
    result = copy.deepcopy(profile)
    if result.get("schema_version") != "career-profile-v1":
        raise CandidateError("候选人事实必须使用 career-profile-v1")
    if result.get("review_state") != "reviewed":
        raise CandidateError("候选人事实尚未审核，不能生成投递材料")
    if not result.get("profile_id") or not result.get("version"):
        raise CandidateError("候选人事实缺少 profile_id/version")
    if not isinstance(result.get("identity"), dict) or not result["identity"].get("name"):
        raise CandidateError("候选人姓名缺失")
    facts = result.get("facts")
    if not isinstance(facts, list) or not facts:
        raise CandidateError("候选人审核事实为空")
    seen: set[str] = set()
    for fact in facts:
        fact_id = fact.get("id")
        if not isinstance(fact_id, str) or not fact_id or fact_id in seen:
            raise CandidateError(f"事实 ID 缺失或重复：{fact_id}")
        seen.add(fact_id)
        if fact.get("review_state") != "reviewed" or not fact.get("version"):
            raise CandidateError(f"事实尚未审核或缺版本：{fact_id}")
        if not isinstance(fact.get("text"), str) or not fact["text"].strip():
            raise CandidateError(f"事实原句为空：{fact_id}")
        variants = fact.setdefault("approved_variants", [])
        if not isinstance(variants, list) or any(not isinstance(v, str) or not v.strip() for v in variants):
            raise CandidateError(f"批准变体必须是非空字符串列表：{fact_id}")
        if verify_sources:
            fact["source"] = _check_source(fact.get("source"), profile_path)
    for cap in result.get("capabilities", []):
        if cap.get("status") not in STATUSES or not cap.get("id"):
            raise CandidateError("能力必须声明 ID 和 direct/partial/unknown/not_met")
        if not cap.get("aliases") or not isinstance(cap["aliases"], list):
            raise CandidateError(f"能力缺少明确匹配词：{cap.get('id')}")
        ids = cap.get("fact_ids", [])
        if any(i not in seen for i in ids):
            raise CandidateError(f"能力引用了不存在的事实：{cap['id']}")
        if cap["status"] in {"direct", "partial"} and not ids:
            raise CandidateError(f"能力证据不能只依靠名称：{cap['id']}")
    for gap in result.get("gaps", []):
        if gap.get("status") not in {"not_met", "unknown"} or not gap.get("aliases"):
            raise CandidateError("gap 必须区分明确没做与未知，而且标明具体范围")
    for key in ("intro_fact_ids", "primary_fact_ids", "evidence_fact_ids", "required_fact_ids",
                "skill_fact_ids", "availability_fact_ids"):
        if any(i not in seen for i in result.get("materials", {}).get(key, [])):
            raise CandidateError(f"材料 {key} 引用了不存在的事实")
    baseline = result.get("baseline", {})
    if not baseline.get("path") or not baseline.get("version"):
        raise CandidateError("缺少用户原始简历 baseline.path/version")
    if verify_sources:
        path = resolve_evidence_path(baseline["path"], profile_path)
        actual = sha256_bytes(path.read_bytes())
        if baseline.get("sha256") != actual:
            raise CandidateError("原始简历哈希不符，禁止生成伪基线 diff")
        baseline["resolved_path"] = str(path)
        result["baseline_hash"] = actual
    result["_facts_by_id"] = {f["id"]: f for f in facts}
    return result


def load_candidate(path: str | Path | None = None) -> dict:
    profile_path = Path(path or DEFAULT_PROFILE).resolve()
    if not profile_path.is_relative_to(WORKSPACE_ROOT.resolve()):
        raise CandidateError("候选人事实必须来自已授权本地工作区")
    try:
        raw = profile_path.read_bytes()
        profile = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CandidateError(f"无法读取候选人事实：{profile_path}: {error}") from error
    candidate = validate_candidate(profile, profile_path=profile_path)
    candidate["candidate_hash"] = sha256_bytes(raw)
    candidate["_content_hash"] = canonical_hash(profile)
    candidate["_profile_path"] = str(profile_path)
    return candidate


def verify_candidate_current(candidate: dict) -> None:
    """Detect edits to profile, baseline, and fact sources after loading."""
    if candidate.get("_profile_path"):
        path = Path(candidate["_profile_path"])
        if sha256_bytes(path.read_bytes()) != candidate.get("candidate_hash"):
            raise CandidateError("候选人审核 JSON 已变化，须重新加载并审核材料")
        clean = {key: copy.deepcopy(value) for key, value in candidate.items()
                 if not key.startswith("_") and key not in {"candidate_hash", "baseline_hash"}}
        clean.get("baseline", {}).pop("resolved_path", None)
        for fact in clean.get("facts", []):
            fact.get("source", {}).pop("resolved_path", None)
        # Loading may add an empty approved_variants list, which is part of this schema.
        disk = json.loads(path.read_text(encoding="utf-8-sig"))
        for fact in disk.get("facts", []):
            fact.setdefault("approved_variants", [])
        if canonical_hash(clean) != canonical_hash(disk):
            raise CandidateError("内存中的候选人事实被修改，不能以原JSON哈希包装新增主张")
    else:
        raise CandidateError("投递材料只能使用load_candidate读取的审核JSON，不能使用无来源内存事实")
    baseline = candidate.get("baseline", {})
    path = resolve_evidence_path(baseline["path"], Path(candidate["_profile_path"]) if candidate.get("_profile_path") else None)
    if sha256_bytes(path.read_bytes()) != baseline.get("sha256"):
        raise CandidateError("原始简历已变化，禁止沿用旧 diff")
    for fact in candidate.get("facts", []):
        _check_source(fact["source"], Path(candidate["_profile_path"]) if candidate.get("_profile_path") else None)


def approved_text(candidate: dict, fact_id: str, variant: str | None = None) -> str:
    # Derived indexes are conveniences, never a second authority for claim text.
    fact = next((f for f in candidate.get("facts", []) if f["id"] == fact_id), None)
    if fact is None or fact.get("review_state") != "reviewed":
        raise CandidateError(f"不能使用未审核事实：{fact_id}")
    text = variant if variant is not None else fact["text"]
    if text not in [fact["text"], *fact.get("approved_variants", [])]:
        raise CandidateError(f"句子不是已批准原句或变体：{fact_id}")
    return text
