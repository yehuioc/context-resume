"""SQLite authority for opportunities, immutable evidence and real applications."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "private" / "career-ops.sqlite3"
VERIFIED_STATUSES = {"employer_verified", "official_platform_live"}
CONFIRMATION_TYPES = {"user_confirmation", "platform_receipt"}
INTERACTION_TYPES = {"hr_reply", "hiring_manager_reply", "interview", "rejected", "offer", "withdrawn", "no_response", "note"}
REQUIRED_ARTIFACTS = {"jd", "assessment", "resume_md", "resume_html", "resume_pdf", "claim_audit", "diff", "baseline", "greeting", "email", "intro", "evidence", "manifest"}


class StateError(ValueError):
    """An explicit human boundary or state invariant was not met."""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized_url(value: str) -> str:
    if not value:
        return ""
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return ""
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(sorted(query)), ""))


SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
 id INTEGER PRIMARY KEY, company TEXT NOT NULL, role_title TEXT NOT NULL, location TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'discovered', current_revision_id INTEGER REFERENCES jd_revisions(id), current_observed_at TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jd_revisions (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
 jd_hash TEXT NOT NULL, revision_digest TEXT NOT NULL, payload_json TEXT NOT NULL,
 verification_status TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(opportunity_id,revision_digest)
);
CREATE TABLE IF NOT EXISTS source_aliases (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
 identity_kind TEXT NOT NULL, identity_value TEXT NOT NULL, source_channel TEXT NOT NULL,
 source_url TEXT NOT NULL, external_id TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(identity_kind,identity_value)
);
CREATE TABLE IF NOT EXISTS observations (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
 revision_id INTEGER NOT NULL REFERENCES jd_revisions(id), observation_digest TEXT NOT NULL UNIQUE,
 payload_json TEXT NOT NULL, observed_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assessments (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
 revision_id INTEGER NOT NULL REFERENCES jd_revisions(id), candidate_hash TEXT NOT NULL,
 assessment_digest TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('suggested_shortlist','hold','reject')),
 eligible INTEGER NOT NULL CHECK(eligible IN (0,1)), payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(opportunity_id,revision_id,candidate_hash,assessment_digest)
);
CREATE TABLE IF NOT EXISTS packets (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
 revision_id INTEGER NOT NULL REFERENCES jd_revisions(id), assessment_id INTEGER NOT NULL REFERENCES assessments(id),
 candidate_hash TEXT NOT NULL, jd_hash TEXT NOT NULL, packet_digest TEXT NOT NULL UNIQUE,
 payload_json TEXT NOT NULL, artifacts_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_decisions (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
 revision_id INTEGER NOT NULL REFERENCES jd_revisions(id), candidate_hash TEXT NOT NULL,
 decision TEXT NOT NULL CHECK(decision IN ('shortlist','hold','reject')), actor TEXT NOT NULL CHECK(length(trim(actor))>0),
 note TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
 packet_id INTEGER NOT NULL REFERENCES packets(id), human_decision_id INTEGER NOT NULL REFERENCES human_decisions(id),
 packet_digest TEXT NOT NULL, jd_hash TEXT NOT NULL, candidate_hash TEXT NOT NULL,
 accepts_unknowns INTEGER NOT NULL DEFAULT 0 CHECK(accepts_unknowns IN (0,1)),
 unknowns_json TEXT NOT NULL DEFAULT '[]', review_note TEXT NOT NULL DEFAULT '',
 actor TEXT NOT NULL CHECK(length(trim(actor))>0), note TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(packet_id,human_decision_id)
);
CREATE TABLE IF NOT EXISTS applications (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL UNIQUE REFERENCES opportunities(id),
 packet_id INTEGER NOT NULL UNIQUE REFERENCES packets(id), approval_id INTEGER NOT NULL UNIQUE REFERENCES approvals(id),
 confirmation_type TEXT NOT NULL CHECK(confirmation_type IN ('user_confirmation','platform_receipt')),
 evidence TEXT NOT NULL CHECK(length(trim(evidence))>0), sent_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contacts (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
 name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('hr','hiring_manager','other')),
 channel TEXT NOT NULL, address TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(opportunity_id,name,role,channel,address)
);
CREATE TABLE IF NOT EXISTS interactions (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id), application_id INTEGER REFERENCES applications(id),
 contact_id INTEGER REFERENCES contacts(id), interaction_type TEXT NOT NULL,
 content TEXT NOT NULL CHECK(length(trim(content))>0), occurred_at TEXT NOT NULL,
 interaction_digest TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS next_actions (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
 action TEXT NOT NULL CHECK(length(trim(action))>0), due_at TEXT NOT NULL, completed_at TEXT,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER REFERENCES opportunities(id),
 event_type TEXT NOT NULL, detail_json TEXT NOT NULL, event_key TEXT UNIQUE,
 occurred_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS legacy_records (
 id INTEGER PRIMARY KEY, source_path TEXT NOT NULL, table_name TEXT NOT NULL,
 legacy_id TEXT NOT NULL, record_digest TEXT NOT NULL, payload_json TEXT NOT NULL,
 opportunity_id INTEGER REFERENCES opportunities(id), imported_at TEXT NOT NULL,
 UNIQUE(source_path,table_name,legacy_id,record_digest)
);
CREATE TRIGGER IF NOT EXISTS approval_guard BEFORE INSERT ON approvals BEGIN
 SELECT CASE WHEN NOT EXISTS (
  SELECT 1 FROM packets p JOIN opportunities o ON o.id=p.opportunity_id
  JOIN jd_revisions r ON r.id=p.revision_id JOIN assessments s ON s.id=p.assessment_id
  JOIN human_decisions h ON h.id=NEW.human_decision_id
  WHERE p.id=NEW.packet_id AND p.opportunity_id=NEW.opportunity_id
   AND o.current_revision_id=p.revision_id AND p.packet_digest=NEW.packet_digest
   AND p.jd_hash=NEW.jd_hash AND p.candidate_hash=NEW.candidate_hash
   AND (s.eligible=1 OR (NEW.accepts_unknowns=1 AND s.decision='hold' AND length(trim(NEW.review_note))>0))
   AND json_array_length(json_extract(s.payload_json,'$.hard_conflicts'))=0
   AND r.verification_status IN ('employer_verified','official_platform_live')
   AND length(trim(json_extract(r.payload_json,'$.jd_raw')))>0
   AND (length(trim(COALESCE(json_extract(r.payload_json,'$.official_url'),'')))>0 OR (r.verification_status='official_platform_live' AND length(trim(COALESCE(json_extract(r.payload_json,'$.source_url'),'')))>0))
   AND h.opportunity_id=o.id AND h.revision_id=r.id AND h.candidate_hash=p.candidate_hash
   AND h.decision='shortlist'
   AND h.id=(SELECT MAX(id) FROM human_decisions WHERE opportunity_id=o.id)
   AND s.id=(SELECT MAX(id) FROM assessments WHERE opportunity_id=o.id AND revision_id=r.id AND candidate_hash=p.candidate_hash)
 ) THEN RAISE(ABORT,'approval requires current verified eligible packet and human shortlist') END;
END;
CREATE TRIGGER IF NOT EXISTS application_guard BEFORE INSERT ON applications BEGIN
 SELECT CASE WHEN NOT EXISTS (
  SELECT 1 FROM approvals a JOIN packets p ON p.id=a.packet_id
  JOIN opportunities o ON o.id=p.opportunity_id JOIN assessments s ON s.id=p.assessment_id
  JOIN human_decisions h ON h.id=a.human_decision_id JOIN jd_revisions r ON r.id=p.revision_id
  WHERE a.id=NEW.approval_id AND p.id=NEW.packet_id AND o.id=NEW.opportunity_id
   AND o.current_revision_id=p.revision_id AND a.packet_digest=p.packet_digest
   AND a.jd_hash=p.jd_hash AND a.candidate_hash=p.candidate_hash
   AND (s.eligible=1 OR (a.accepts_unknowns=1 AND s.decision='hold' AND length(trim(a.review_note))>0))
   AND json_array_length(json_extract(s.payload_json,'$.hard_conflicts'))=0
   AND r.verification_status IN ('employer_verified','official_platform_live')
   AND length(trim(json_extract(r.payload_json,'$.jd_raw')))>0
   AND h.id=(SELECT MAX(id) FROM human_decisions WHERE opportunity_id=o.id) AND h.decision='shortlist'
   AND s.id=(SELECT MAX(id) FROM assessments WHERE opportunity_id=o.id AND revision_id=r.id AND candidate_hash=p.candidate_hash)
 ) THEN RAISE(ABORT,'application requires current approval and confirmed sending evidence') END;
END;
"""


class Store:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        for table in ("jd_revisions", "observations", "assessments", "packets", "human_decisions", "approvals", "applications", "interactions", "events", "legacy_records"):
            for verb in ("UPDATE", "DELETE"):
                self.conn.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{verb.lower()} BEFORE {verb} ON {table} BEGIN SELECT RAISE(ABORT,'immutable {table}'); END")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _event(self, opportunity_id: int | None, event_type: str, detail: dict, *, key: str | None = None, occurred_at: str | None = None) -> None:
        self.conn.execute("INSERT OR IGNORE INTO events(opportunity_id,event_type,detail_json,event_key,occurred_at,created_at) VALUES(?,?,?,?,?,?)",
                          (opportunity_id, event_type, canonical_json(detail), key, occurred_at or now_iso(), now_iso()))

    def ingest_observation(self, observation: dict[str, Any]) -> dict:
        obs = dict(observation)
        company, title = str(obs.get("company", "")).strip(), str(obs.get("role_title", obs.get("title", ""))).strip()
        if not company or not title:
            raise StateError("岗位必须包含公司和职位名称")
        obs["company"], obs["role_title"] = company, title
        raw = str(obs.get("jd_raw", obs.get("jd_text", obs.get("description", ""))))
        computed = text_hash(raw)
        if obs.get("jd_hash") and obs["jd_hash"] != computed:
            raise StateError("JD 哈希与原始正文不一致")
        obs["jd_raw"], obs["jd_hash"] = raw, computed
        channel, external_id = str(obs.get("source_channel", "manual")), str(obs.get("external_id") or "")
        location = str(obs.get("location") or "unknown")
        verification = str(obs.get("verification_status", "unknown"))
        obs["verification_status"] = verification
        source_url = normalized_url(str(obs.get("source_url") or ""))
        identities = []
        official = normalized_url(str(obs.get("official_url") or ""))
        if official and verification == "employer_verified" and obs.get("verification_evidence"):
            identities.append(("official_url", official))
        if external_id:
            identities.append(("platform_id", canonical_json([channel, external_id])))
        if source_url:
            identities.append(("source_url", canonical_json([channel, source_url, company, title, location])))
        if not identities:
            identities.append(("content", digest([channel, company, title, location, raw])))
        observed_at = str(obs.get("observed_at") or now_iso())
        obs.setdefault("observed_at", observed_at)
        observation_digest = digest(obs)
        # Retrieval timestamps and source-specific payload do not create new JD versions.
        revision_payload = {k: v for k, v in obs.items() if k not in {"observed_at", "source_payload", "source_channel", "source_url", "external_id", "verification_evidence"}}
        revision_digest = digest(revision_payload)
        with self.conn:
            seen = self.conn.execute("SELECT opportunity_id,revision_id FROM observations WHERE observation_digest=?", (observation_digest,)).fetchone()
            if seen:
                return {**dict(seen), "created": False, "revised": False}
            matches = {r[0] for kind, value in identities for r in self.conn.execute("SELECT opportunity_id FROM source_aliases WHERE identity_kind=? AND identity_value=?", (kind, value))}
            if len(matches) > 1:
                raise StateError("来源标识指向多个机会，需要人工解决；不会自动合并")
            created = not matches
            if created:
                cursor = self.conn.execute("INSERT INTO opportunities(company,role_title,location,created_at,updated_at) VALUES(?,?,?,?,?)", (company, title, location, now_iso(), now_iso()))
                opportunity_id = cursor.lastrowid
                previous = None
                previous_observed_at = None
            else:
                opportunity_id = next(iter(matches))
                prior = self.conn.execute("SELECT current_revision_id,current_observed_at FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
                previous, previous_observed_at = prior[0], prior[1]
            for kind, value in identities:
                self.conn.execute("INSERT OR IGNORE INTO source_aliases(opportunity_id,identity_kind,identity_value,source_channel,source_url,external_id,created_at) VALUES(?,?,?,?,?,?,?)", (opportunity_id, kind, value, channel, source_url, external_id, now_iso()))
            self.conn.execute("INSERT OR IGNORE INTO jd_revisions(opportunity_id,jd_hash,revision_digest,payload_json,verification_status,created_at) VALUES(?,?,?,?,?,?)", (opportunity_id, computed, revision_digest, canonical_json(obs), verification, now_iso()))
            revision_id = self.conn.execute("SELECT id FROM jd_revisions WHERE opportunity_id=? AND revision_digest=?", (opportunity_id, revision_digest)).fetchone()[0]
            def timestamp(value: str | None) -> dt.datetime | None:
                try:
                    parsed = dt.datetime.fromisoformat((value or "").replace("Z", "+00:00"))
                    return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed
                except ValueError:
                    return None
            old_time, new_time = timestamp(previous_observed_at), timestamp(observed_at)
            # Source receipts currently have second precision. An unseen newer
            # revision at that second can be a real failed/closed check; only a
            # known older revision must not roll current state back at a tie.
            stale = previous is not None and old_time is not None and (new_time is None or new_time < old_time or (new_time == old_time and revision_id < previous))
            revised = not stale and previous is not None and previous != revision_id
            self.conn.execute("INSERT INTO observations(opportunity_id,revision_id,observation_digest,payload_json,observed_at,created_at) VALUES(?,?,?,?,?,?)", (opportunity_id, revision_id, observation_digest, canonical_json(obs), observed_at, now_iso()))
            if not stale:
                self.conn.execute("UPDATE opportunities SET current_revision_id=?,current_observed_at=?,company=?,role_title=?,location=?,updated_at=?,status=CASE WHEN ? AND id NOT IN (SELECT opportunity_id FROM applications) THEN 'discovered' ELSE status END WHERE id=?", (revision_id, observed_at, company, title, location, now_iso(), revised, opportunity_id))
            self._event(opportunity_id, "stale_observation" if stale else ("discovered" if created else ("jd_revised" if revised else "observed")), {"revision_id": revision_id, "jd_hash": computed, "source_channel": channel}, key="observation:" + observation_digest, occurred_at=observed_at)
        return {"opportunity_id": opportunity_id, "revision_id": revision_id, "current_revision_id": previous if stale else revision_id, "created": created, "revised": revised, "stale": stale}

    def get_opportunity(self, opportunity_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
        if not row:
            raise StateError(f"机会不存在：{opportunity_id}")
        result = dict(row)
        revision = self.conn.execute("SELECT * FROM jd_revisions WHERE id=?", (row["current_revision_id"],)).fetchone()
        result["revision"] = dict(revision) if revision else None
        latest_observation = self.conn.execute("SELECT payload_json FROM observations WHERE opportunity_id=? AND revision_id=? ORDER BY observed_at DESC,id DESC LIMIT 1", (opportunity_id, row["current_revision_id"])).fetchone()
        result["observation"] = json.loads(latest_observation[0]) if latest_observation else (json.loads(revision["payload_json"]) if revision else {})
        result["aliases"] = [dict(r) for r in self.conn.execute("SELECT * FROM source_aliases WHERE opportunity_id=? ORDER BY id", (opportunity_id,))]
        result["assessments"] = [dict(r) | {"payload": json.loads(r["payload_json"])} for r in self.conn.execute("SELECT * FROM assessments WHERE opportunity_id=? ORDER BY id DESC", (opportunity_id,))]
        result["packets"] = [dict(r) | {"payload": json.loads(r["payload_json"]), "artifacts": json.loads(r["artifacts_json"])} for r in self.conn.execute("SELECT * FROM packets WHERE opportunity_id=? ORDER BY id DESC", (opportunity_id,))]
        result["human_decisions"] = [dict(r) for r in self.conn.execute("SELECT * FROM human_decisions WHERE opportunity_id=? ORDER BY id", (opportunity_id,))]
        result["approvals"] = [dict(r) for r in self.conn.execute("SELECT * FROM approvals WHERE opportunity_id=? ORDER BY id", (opportunity_id,))]
        result["application"] = next((dict(r) for r in self.conn.execute("SELECT * FROM applications WHERE opportunity_id=?", (opportunity_id,))), None)
        result["events"] = [dict(r) | {"detail": json.loads(r["detail_json"])} for r in self.conn.execute("SELECT * FROM events WHERE opportunity_id=? ORDER BY id", (opportunity_id,))]
        result["contacts"] = [dict(r) for r in self.conn.execute("SELECT * FROM contacts WHERE opportunity_id=?", (opportunity_id,))]
        result["next_actions"] = [dict(r) for r in self.conn.execute("SELECT * FROM next_actions WHERE opportunity_id=? ORDER BY id", (opportunity_id,))]
        result["interactions"] = [dict(r) for r in self.conn.execute("SELECT * FROM interactions WHERE opportunity_id=? ORDER BY occurred_at,id", (opportunity_id,))]
        return result

    def list_opportunities(self, *, status: str | None = None, limit: int = 100) -> list[dict]:
        sql = "SELECT o.*,r.jd_hash,r.verification_status,(SELECT decision FROM assessments s WHERE s.opportunity_id=o.id AND s.revision_id=o.current_revision_id ORDER BY s.id DESC LIMIT 1) suggested_decision FROM opportunities o JOIN jd_revisions r ON r.id=o.current_revision_id"
        params: list[Any] = []
        if status:
            sql += " WHERE o.status=?"
            params.append(status)
        sql += " ORDER BY o.id LIMIT ?"
        params.append(max(1, min(int(limit), 10000)))
        return [dict(r) for r in self.conn.execute(sql, params)]

    def save_assessment(self, opportunity_id: int, candidate_hash: str, assessment: dict) -> int:
        opportunity = self.get_opportunity(opportunity_id)
        data = dict(assessment)
        decision = data.get("decision", "hold")
        if decision not in {"suggested_shortlist", "hold", "reject"}:
            raise StateError("匹配结果不能直接成为人工shortlist或applied")
        eligible = decision == "suggested_shortlist" and not data.get("hard_conflicts") and not data.get("unknown_required") and opportunity["revision"]["verification_status"] == "employer_verified" and bool(opportunity["observation"].get("jd_raw", "").strip())
        fingerprint = digest(data)
        state = "suggested_reject" if decision == "reject" else ("suggested_shortlist" if eligible else "hold")
        with self.conn:
            existing = self.conn.execute("SELECT id FROM assessments WHERE opportunity_id=? AND revision_id=? AND candidate_hash=? AND assessment_digest=?", (opportunity_id, opportunity["current_revision_id"], candidate_hash, fingerprint)).fetchone()
            if existing:
                # Reconcile old autonomous labels without overwriting any human
                # choice, approval or confirmed application on a replay.
                latest = self.conn.execute("SELECT MAX(id) FROM assessments WHERE opportunity_id=? AND revision_id=? AND candidate_hash=?", (opportunity_id, opportunity["current_revision_id"], candidate_hash)).fetchone()[0]
                if latest == existing[0]:
                    self.conn.execute("UPDATE opportunities SET status=?,updated_at=? WHERE id=? AND status IN ('discovered','hold','suggested_shortlist','suggested_reject') AND id NOT IN (SELECT opportunity_id FROM human_decisions UNION SELECT opportunity_id FROM approvals UNION SELECT opportunity_id FROM applications)", (state, now_iso(), opportunity_id))
                return existing[0]
            self.conn.execute("INSERT OR IGNORE INTO assessments(opportunity_id,revision_id,candidate_hash,assessment_digest,decision,eligible,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (opportunity_id, opportunity["current_revision_id"], candidate_hash, fingerprint, decision, int(eligible), canonical_json(data), now_iso()))
            assessment_id = self.conn.execute("SELECT id FROM assessments WHERE opportunity_id=? AND revision_id=? AND candidate_hash=? AND assessment_digest=?", (opportunity_id, opportunity["current_revision_id"], candidate_hash, fingerprint)).fetchone()[0]
            self._event(opportunity_id, "assessed", {"assessment_id": assessment_id, "decision": decision, "eligible": eligible}, key=f"assessment:{assessment_id}")
            self.conn.execute("UPDATE opportunities SET status=?,updated_at=? WHERE id=? AND id NOT IN (SELECT opportunity_id FROM applications)", (state, now_iso(), opportunity_id))
        return assessment_id

    def save_packet(self, opportunity_id: int, assessment_id: int, candidate_hash: str, payload: dict, artifacts: dict[str, dict]) -> int:
        opportunity = self.get_opportunity(opportunity_id)
        assessment = self.conn.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone()
        if not assessment or assessment["opportunity_id"] != opportunity_id or assessment["revision_id"] != opportunity["current_revision_id"] or assessment["candidate_hash"] != candidate_hash:
            raise StateError("材料包必须绑定当前JD与本次候选人匹配结果")
        if payload.get("candidate_hash") and payload["candidate_hash"] != candidate_hash:
            raise StateError("材料包候选人哈希不一致")
        if payload.get("jd_hash") and payload["jd_hash"] != opportunity["revision"]["jd_hash"]:
            raise StateError("材料包JD哈希不一致")
        missing = REQUIRED_ARTIFACTS - set(artifacts)
        if missing or payload.get("status") != "review_ready":
            raise StateError("材料包未完整达到review_ready：" + ",".join(sorted(missing)))
        for label, artifact in artifacts.items():
            path = Path(artifact["path"])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise StateError(f"材料包保存时文件摘要不一致：{label}")
        packet_digest = digest({"payload": payload, "artifacts": artifacts, "revision_id": opportunity["current_revision_id"], "assessment_id": assessment_id, "candidate_hash": candidate_hash, "jd_hash": opportunity["revision"]["jd_hash"]})
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO packets(opportunity_id,revision_id,assessment_id,candidate_hash,jd_hash,packet_digest,payload_json,artifacts_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (opportunity_id, opportunity["current_revision_id"], assessment_id, candidate_hash, opportunity["revision"]["jd_hash"], packet_digest, canonical_json(payload), canonical_json(artifacts), now_iso()))
            packet_id = self.conn.execute("SELECT id FROM packets WHERE packet_digest=?", (packet_digest,)).fetchone()[0]
            self._event(opportunity_id, "review_package", {"packet_id": packet_id, "packet_digest": packet_digest}, key=f"packet:{packet_id}")
        return packet_id

    def get_packet(self, packet_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM packets WHERE id=?", (packet_id,)).fetchone()
        if not row:
            raise StateError(f"材料包不存在：{packet_id}")
        return dict(row) | {"payload": json.loads(row["payload_json"]), "artifacts": json.loads(row["artifacts_json"])}

    def verify_packet(self, packet_id: int, candidate_hash: str, *, allow_unknowns: bool = False) -> dict:
        packet = self.get_packet(packet_id)
        opportunity = self.get_opportunity(packet["opportunity_id"])
        if packet["revision_id"] != opportunity["current_revision_id"] or packet["jd_hash"] != opportunity["revision"]["jd_hash"]:
            raise StateError("JD或来源核验已更新，本次材料包和批准已失效")
        if candidate_hash != packet["candidate_hash"]:
            raise StateError("候选人事实已更新，本次材料包和批准已失效")
        expected = digest({"payload": packet["payload"], "artifacts": packet["artifacts"], "revision_id": packet["revision_id"], "assessment_id": packet["assessment_id"], "candidate_hash": packet["candidate_hash"], "jd_hash": packet["jd_hash"]})
        if expected != packet["packet_digest"]:
            raise StateError("材料包摘要校验失败")
        if not packet["artifacts"]:
            raise StateError("材料包没有可核对的文件")
        for label, artifact in packet["artifacts"].items():
            path = Path(artifact["path"])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise StateError(f"材料包文件已修改或丢失：{label}")
        assessment = self.conn.execute("SELECT * FROM assessments WHERE id=?", (packet["assessment_id"],)).fetchone()
        latest = self.conn.execute("SELECT MAX(id) FROM assessments WHERE opportunity_id=? AND revision_id=? AND candidate_hash=?", (packet["opportunity_id"], packet["revision_id"], candidate_hash)).fetchone()[0]
        assessment_payload = json.loads(assessment["payload_json"])
        observation = opportunity["observation"]
        source_status = opportunity["revision"]["verification_status"]
        has_entry = bool(normalized_url(str(observation.get("official_url") or ""))) or (source_status == "official_platform_live" and bool(normalized_url(str(observation.get("source_url") or ""))))
        if latest != assessment["id"] or assessment_payload.get("hard_conflicts") or source_status not in VERIFIED_STATUSES or not has_entry or not observation.get("jd_raw", "").strip():
            raise StateError("有硬条件冲突、岗位关闭/核验失败、缺JD/入口或匹配已更新，不能批准/登记投递")
        if not assessment["eligible"] and not (allow_unknowns and assessment["decision"] == "hold"):
            raise StateError("本岗位仍有Unknown/风险；必须明确accept-unknowns并填写review-note后才可人工接受")
        return packet

    def human_decision(self, opportunity_id: int, candidate_hash: str, decision: str, *, actor: str, note: str = "") -> int:
        if decision not in {"shortlist", "hold", "reject"} or not actor.strip():
            raise StateError("人工决定必须为shortlist/hold/reject且填写操作者")
        opportunity = self.get_opportunity(opportunity_id)
        with self.conn:
            cursor = self.conn.execute("INSERT INTO human_decisions(opportunity_id,revision_id,candidate_hash,decision,actor,note,created_at) VALUES(?,?,?,?,?,?,?)", (opportunity_id, opportunity["current_revision_id"], candidate_hash, decision, actor, note, now_iso()))
            self._event(opportunity_id, "human_" + decision, {"human_decision_id": cursor.lastrowid, "actor": actor, "note": note})
            self.conn.execute("UPDATE opportunities SET status=?,updated_at=? WHERE id=? AND id NOT IN (SELECT opportunity_id FROM applications)", ("human_shortlisted" if decision == "shortlist" else decision, now_iso(), opportunity_id))
        return cursor.lastrowid

    def approve(self, packet_id: int, candidate_hash: str, *, actor: str, note: str = "", accept_unknowns: bool = False, review_note: str = "") -> int:
        if accept_unknowns and not review_note.strip():
            raise StateError("accept-unknowns必须填写非空review-note，保留未确认条件及接受理由")
        packet = self.verify_packet(packet_id, candidate_hash, allow_unknowns=accept_unknowns)
        human = self.conn.execute("SELECT * FROM human_decisions WHERE opportunity_id=? ORDER BY id DESC LIMIT 1", (packet["opportunity_id"],)).fetchone()
        if not human or human["decision"] != "shortlist" or human["revision_id"] != packet["revision_id"] or human["candidate_hash"] != candidate_hash:
            raise StateError("尚未人工shortlist当前JD与候选人版本")
        existing = self.conn.execute("SELECT id FROM approvals WHERE packet_id=? AND human_decision_id=?", (packet_id, human["id"])).fetchone()
        if existing:
            return existing[0]
        assessment_payload = json.loads(self.conn.execute("SELECT payload_json FROM assessments WHERE id=?", (packet["assessment_id"],)).fetchone()[0])
        with self.conn:
            cursor = self.conn.execute("INSERT INTO approvals(opportunity_id,packet_id,human_decision_id,packet_digest,jd_hash,candidate_hash,accepts_unknowns,unknowns_json,review_note,actor,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (packet["opportunity_id"], packet_id, human["id"], packet["packet_digest"], packet["jd_hash"], candidate_hash, int(accept_unknowns), canonical_json(assessment_payload.get("unknown_required", [])), review_note, actor, note, now_iso()))
            self._event(packet["opportunity_id"], "approved", {"approval_id": cursor.lastrowid, "packet_id": packet_id, "packet_digest": packet["packet_digest"], "actor": actor, "accepts_unknowns": accept_unknowns, "unknowns": assessment_payload.get("unknown_required", []), "review_note": review_note})
            self.conn.execute("UPDATE opportunities SET status='approved',updated_at=? WHERE id=? AND id NOT IN (SELECT opportunity_id FROM applications)", (now_iso(), packet["opportunity_id"]))
        return cursor.lastrowid

    def mark_applied(self, packet_id: int, candidate_hash: str, *, confirmation_type: str, evidence: str, sent_at: str | None = None) -> int:
        if confirmation_type not in CONFIRMATION_TYPES or not evidence.strip():
            raise StateError("真实投递需要用户确认或平台回执及非空证据；批准不等于发送")
        approval = self.conn.execute("SELECT * FROM approvals WHERE packet_id=? ORDER BY id DESC LIMIT 1", (packet_id,)).fetchone()
        if not approval:
            raise StateError("材料包尚未人工批准")
        packet = self.verify_packet(packet_id, candidate_hash, allow_unknowns=bool(approval["accepts_unknowns"]))
        latest_human = self.conn.execute("SELECT * FROM human_decisions WHERE opportunity_id=? ORDER BY id DESC LIMIT 1", (packet["opportunity_id"],)).fetchone()
        if not latest_human or latest_human["decision"] != "shortlist" or latest_human["id"] != approval["human_decision_id"]:
            raise StateError("人工决定已变更或撤销；重新shortlist后必须再次批准本材料包")
        existing = self.conn.execute("SELECT * FROM applications WHERE opportunity_id=?", (packet["opportunity_id"],)).fetchone()
        if existing:
            if existing["packet_id"] != packet_id:
                raise StateError("该机会已登记真实投递，不能覆盖材料版本")
            return existing["id"]
        with self.conn:
            cursor = self.conn.execute("INSERT INTO applications(opportunity_id,packet_id,approval_id,confirmation_type,evidence,sent_at,created_at) VALUES(?,?,?,?,?,?,?)", (packet["opportunity_id"], packet_id, approval["id"], confirmation_type, evidence, sent_at or now_iso(), now_iso()))
            self._event(packet["opportunity_id"], "applied", {"application_id": cursor.lastrowid, "packet_id": packet_id, "confirmation_type": confirmation_type, "evidence": evidence}, key=f"application:{cursor.lastrowid}", occurred_at=sent_at)
            self.conn.execute("UPDATE opportunities SET status='applied',updated_at=? WHERE id=?", (now_iso(), packet["opportunity_id"]))
        return cursor.lastrowid

    def record_interaction(self, opportunity_id: int, interaction_type: str, content: str, *, occurred_at: str | None = None, event_id: str | None = None, contact: dict | None = None, next_action: str | None = None, due_at: str | None = None) -> int:
        if interaction_type not in INTERACTION_TYPES or not content.strip():
            raise StateError("回复类型或内容无效")
        application = self.conn.execute("SELECT id FROM applications WHERE opportunity_id=?", (opportunity_id,)).fetchone()
        self.get_opportunity(opportunity_id)
        occurrence = occurred_at or now_iso()
        # No timestamp: stable replay detection. A distinct repeat requires event-id or timestamp.
        fingerprint = digest([opportunity_id, event_id] if event_id else [opportunity_id, interaction_type, content, occurred_at, contact])
        existing_interaction = self.conn.execute("SELECT * FROM interactions WHERE interaction_digest=?", (fingerprint,)).fetchone()
        if event_id and existing_interaction and (existing_interaction["interaction_type"] != interaction_type or existing_interaction["content"] != content):
            raise StateError("同一event-id已存在不同的不可变回复，不能覆盖")
        if next_action and not due_at:
            raise StateError("下一步行动必须填写due_at")
        with self.conn:
            contact_id = None
            if contact:
                values = (opportunity_id, str(contact.get("name", "")), str(contact.get("role", "other")), str(contact.get("channel", "")), str(contact.get("address", "")))
                self.conn.execute("INSERT OR IGNORE INTO contacts(opportunity_id,name,role,channel,address,created_at) VALUES(?,?,?,?,?,?)", (*values, now_iso()))
                contact_id = self.conn.execute("SELECT id FROM contacts WHERE opportunity_id=? AND name=? AND role=? AND channel=? AND address=?", values).fetchone()[0]
            self.conn.execute("INSERT OR IGNORE INTO interactions(opportunity_id,application_id,contact_id,interaction_type,content,occurred_at,interaction_digest,created_at) VALUES(?,?,?,?,?,?,?,?)", (opportunity_id, application["id"] if application else None, contact_id, interaction_type, content, occurrence, fingerprint, now_iso()))
            interaction_id = self.conn.execute("SELECT id FROM interactions WHERE interaction_digest=?", (fingerprint,)).fetchone()[0]
            if self.conn.execute("SELECT 1 FROM events WHERE event_key=?", (f"interaction:{interaction_id}",)).fetchone():
                return interaction_id
            self._event(opportunity_id, interaction_type, {"interaction_id": interaction_id, "content": content, "contact_id": contact_id}, key=f"interaction:{interaction_id}", occurred_at=occurrence)
            if interaction_type != "note" and application:
                self.conn.execute("UPDATE opportunities SET status=?,updated_at=? WHERE id=?", (interaction_type, now_iso(), opportunity_id))
            if next_action:
                self.conn.execute("INSERT INTO next_actions(opportunity_id,action,due_at,created_at) VALUES(?,?,?,?)", (opportunity_id, next_action, due_at, now_iso()))
        return interaction_id

    def funnel(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        applied = self.conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        stages = {stage: self.conn.execute("SELECT COUNT(DISTINCT opportunity_id) FROM events WHERE event_type=?", (stage,)).fetchone()[0] for stage in ("review_package", "human_shortlist", "approved", "applied")}
        stages.update({stage: self.conn.execute("SELECT COUNT(DISTINCT application_id) FROM interactions WHERE application_id IS NOT NULL AND interaction_type=?", (stage,)).fetchone()[0] for stage in ("hr_reply", "hiring_manager_reply", "interview", "rejected", "offer")})
        effective = self.conn.execute("SELECT COUNT(DISTINCT a.id) FROM applications a JOIN interactions i ON i.application_id=a.id WHERE i.interaction_type IN ('hr_reply','hiring_manager_reply','interview','offer','rejected')").fetchone()[0]
        stages.update(discovered=total, effective_replies=effective)
        pre_application = self.conn.execute("SELECT COUNT(*) FROM interactions WHERE application_id IS NULL").fetchone()[0]
        return {"stages": stages, "pre_application_interactions": pre_application, "current_status": {r[0]: r[1] for r in self.conn.execute("SELECT status,COUNT(*) FROM opportunities GROUP BY status")}, "reply_rate": effective / applied if applied else None, "interview_rate": stages["interview"] / applied if applied else None, "note": "漏斗按不可变事件统计，拒绝不会抹去之前的回复或面试；前置联系人互动单列，仅真实发送确认后的互动进入回复率。"}

    def export_readonly(self) -> dict:
        return {"schema": "career-ops-readonly-v1", "authority": str(self.path), "writable": False, "exported_at": now_iso(), "opportunities": self.list_opportunities(limit=10000), "funnel": self.funnel(), "next_actions": [dict(r) for r in self.conn.execute("SELECT * FROM next_actions WHERE completed_at IS NULL ORDER BY due_at")], "note": "个人工作台只读消费此导出，不能回写或创建第二CRM。"}

    def migrate_legacy(self, path: str | Path) -> dict:
        source_path = Path(path).resolve()
        # A directory migration must not mint a second history identity. Existing
        # aliases (including Windows junctions) still resolve to this same source.
        identities = [Path(r[0]) for r in self.conn.execute("SELECT DISTINCT source_path FROM legacy_records")
                      if Path(r[0]).resolve() == source_path]
        if len(identities) > 1:
            raise StateError("旧记录存在多个来源身份，需要先核对，不能自动重复导入")
        identity_path = identities[0] if identities else source_path
        source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        before = self.conn.execute("SELECT COUNT(*) FROM legacy_records").fetchone()[0]
        counts: dict[str, int] = {}
        id_mapping: dict[tuple[str, str], int] = {}
        try:
            tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            # Both old jobs and leads are retained; platform IDs map them to one opportunity.
            for table in ("jobs", "job_leads"):
                if table not in tables:
                    continue
                rows = [dict(r) for r in source.execute(f"SELECT * FROM {table} ORDER BY id")]
                counts[table] = len(rows)
                for row in rows:
                    obs = {"company": row.get("company") or "历史记录公司未知", "role_title": row.get("title") or "历史职位未知", "source_channel": row.get("provider") or "legacy", "source_url": row.get("source_url") or "", "external_id": str(row.get("external_id") or f"legacy:{table}:{row['id']}"), "location": row.get("city") or "unknown", "jd_raw": row.get("description") or "", "verification_status": "unknown", "verification_evidence": [], "risk_flags": ["legacy_unverified", "legacy_no_jd"] if not (row.get("description") or "").strip() else ["legacy_unverified"], "source_payload": row, "observed_at": row.get("created_at") or "unknown", "legacy_source": str(identity_path)}
                    imported = self.ingest_observation(obs)
                    id_mapping[(table, str(row["id"]))] = imported["opportunity_id"]
                    if row.get("imported_from_job_id") is not None:
                        id_mapping[("jobs", str(row["imported_from_job_id"]))] = imported["opportunity_id"]
                    self._legacy_record(identity_path, table, row, imported["opportunity_id"])
            for table in sorted(tables - {"jobs", "job_leads", "sqlite_sequence"}):
                rows = [dict(r) for r in source.execute(f'SELECT * FROM "{table}"')]
                counts[table] = len(rows)
                for row in rows:
                    opportunity_id = id_mapping.get(("jobs", str(row.get("job_id")))) or id_mapping.get(("job_leads", str(row.get("job_lead_id"))))
                    self._legacy_record(identity_path, table, row, opportunity_id)
                    if table == "events":
                        with self.conn:
                            self._event(opportunity_id, "legacy_event", {"original_event": row, "source_path": str(identity_path)}, key="legacy_event:" + digest([str(identity_path), row]), occurred_at=row.get("created_at") or "unknown")
        finally:
            source.close()
        imported_count = self.conn.execute("SELECT COUNT(*) FROM legacy_records").fetchone()[0] - before
        return {"source": str(source_path), "mode": "read_only", "source_counts": counts, "new_legacy_records": imported_count, "opportunities": len(set(id_mapping.values())), "applications_created": 0, "note": "原事件、简历快照与历史表逐行保留；旧分数和审批不作新批准，历史记录不制造真实投递。"}

    def _legacy_record(self, path: Path, table: str, row: dict, opportunity_id: int | None) -> None:
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO legacy_records(source_path,table_name,legacy_id,record_digest,payload_json,opportunity_id,imported_at) VALUES(?,?,?,?,?,?,?)", (str(path), table, str(row.get("id", digest(row))), digest(row), canonical_json(row), opportunity_id, now_iso()))
