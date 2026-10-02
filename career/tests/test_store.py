import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from career_ops.config import private_path

from career_ops.store import PROJECT_ROOT, REQUIRED_ARTIFACTS, StateError, Store, text_hash


TMP_ROOT = PROJECT_ROOT / "private" / "test-tmp"
TMP_ROOT.mkdir(parents=True, exist_ok=True)


def observation(**overrides):
    value = {"company": "测试公司", "role_title": "AI 工作流实习", "source_channel": "fixture",
             "source_url": "https://jobs.example.org/job/42", "official_url": "https://employer.example.org/careers/42",
             "external_id": "42", "location": "中国广东", "work_mode": "remote", "employment_type": "internship",
             "jd_raw": "使用 Python 和工作流自动化处理运营任务。", "verification_status": "employer_verified",
             "verification_evidence": {"checked_url": "https://employer.example.org/careers/42", "observed_at": "2026-09-30T10:00:00+00:00"},
             "risk_flags": [], "source_payload": {"test_fixture": True}, "observed_at": "2026-09-30T10:00:00+00:00"}
    value.update(overrides)
    value["jd_hash"] = text_hash(value["jd_raw"])
    return value


def assessment(**overrides):
    value = {"decision": "suggested_shortlist", "eligibility_status": "eligible", "hard_conflicts": [], "unknown_required": [], "requirements": [], "rank_score": 30}
    value.update(overrides)
    return value


def packet_fixture(store, root, opportunity_id, candidate_hash="candidate-v1", result=None):
    result = result or assessment()
    assessment_id = store.save_assessment(opportunity_id, candidate_hash, result)
    artifacts = {}
    folder = root / f"packet-{opportunity_id}-{assessment_id}"
    folder.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_ARTIFACTS:
        path = folder / f"{name}.txt"
        path.write_text("isolated-test-fixture " + name, encoding="utf-8")
        artifacts[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}
    job = store.get_opportunity(opportunity_id)
    return store.save_packet(opportunity_id, assessment_id, candidate_hash, {"status": "review_ready", "candidate_hash": candidate_hash, "jd_hash": job["revision"]["jd_hash"], "files": {k: a["path"] for k, a in artifacts.items()}}, artifacts)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TMP_ROOT)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "state.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def setup_packet(self, obs=None, result=None):
        opportunity_id = self.store.ingest_observation(obs or observation())["opportunity_id"]
        return opportunity_id, packet_fixture(self.store, self.root, opportunity_id, result=result)

    def authorize(self, opportunity_id, packet_id, **kwargs):
        self.store.human_decision(opportunity_id, "candidate-v1", "shortlist", actor="test-user")
        return self.store.approve(packet_id, "candidate-v1", actor="test-user", **kwargs)

    def send_fixture(self, packet_id):
        return self.store.mark_applied(packet_id, "candidate-v1", confirmation_type="user_confirmation", evidence="isolated test only; no real send")

    def test_idempotent_and_cross_channel_aliases(self):
        first = self.store.ingest_observation(observation())
        repeated = self.store.ingest_observation(observation())
        cross = self.store.ingest_observation(observation(source_channel="second", external_id="new-id", source_url="https://platform.example.org/123", observed_at="2026-09-30T11:00:00+00:00"))
        self.assertEqual(first["opportunity_id"], repeated["opportunity_id"])
        self.assertEqual(first["opportunity_id"], cross["opportunity_id"])
        self.assertEqual(first["revision_id"], cross["revision_id"])
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)
        self.assertGreaterEqual(len(self.store.get_opportunity(first["opportunity_id"])["aliases"]), 5)

    def test_same_names_different_locations_are_not_merged(self):
        a = self.store.ingest_observation(observation(official_url="", external_id="", location="上海"))
        b = self.store.ingest_observation(observation(official_url="", external_id="", location="深圳"))
        self.assertNotEqual(a["opportunity_id"], b["opportunity_id"])

    def test_conflicting_aliases_roll_back_transaction(self):
        self.store.ingest_observation(observation())
        self.store.ingest_observation(observation(official_url="https://employer.example.org/careers/43", external_id="43", source_url="https://jobs.example.org/job/43"))
        before = self.store.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        with self.assertRaises(StateError):
            self.store.ingest_observation(observation(external_id="43"))
        self.assertEqual(before, self.store.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0])

    def test_hash_mismatch_and_immutability(self):
        obs = observation(); obs["jd_hash"] = "wrong"
        with self.assertRaises(StateError): self.store.ingest_observation(obs)
        self.store.ingest_observation(observation())
        with self.assertRaises(sqlite3.IntegrityError): self.store.conn.execute("UPDATE jd_revisions SET jd_hash='bad'")
        with self.assertRaises(sqlite3.IntegrityError): self.store.conn.execute("DELETE FROM events")

    def test_receipt_time_path_refresh_does_not_invalidate_material(self):
        opportunity_id, packet_id = self.setup_packet()
        self.authorize(opportunity_id, packet_id)
        refreshed = self.store.ingest_observation(observation(observed_at="2026-09-30T11:00:00+00:00", verification_evidence={"observed_at": "fresh", "raw_path": "new-snapshot"}))
        self.assertFalse(refreshed["revised"])
        self.send_fixture(packet_id)

    def test_stale_revision_cannot_reactivate_old_approval(self):
        opportunity_id, packet_id = self.setup_packet()
        self.authorize(opportunity_id, packet_id)
        fresh = self.store.ingest_observation(observation(jd_raw="职位要求已经改变，需要另外的经验。", observed_at="2026-09-30T12:00:00+00:00"))
        replay = self.store.ingest_observation(observation(source_payload={"different_receipt": True}, observed_at="2026-09-30T10:00:01+00:00"))
        self.assertTrue(replay["stale"])
        self.assertEqual(self.store.get_opportunity(opportunity_id)["current_revision_id"], fresh["revision_id"])
        with self.assertRaises(StateError): self.send_fixture(packet_id)

    def test_failed_recheck_in_same_second_invalidates_approval(self):
        opportunity_id, packet_id = self.setup_packet()
        self.authorize(opportunity_id, packet_id)
        check = self.store.ingest_observation(observation(verification_status="failed"))
        self.assertTrue(check["revised"])
        self.assertEqual(self.store.get_opportunity(opportunity_id)["revision"]["verification_status"], "failed")
        with self.assertRaises(StateError): self.send_fixture(packet_id)
        replay = self.store.ingest_observation(observation(source_payload={"replay": True}))
        self.assertTrue(replay["stale"])
        self.assertEqual(self.store.get_opportunity(opportunity_id)["revision"]["verification_status"], "failed")

    def test_jd_candidate_and_file_changes_invalidate_approval(self):
        opportunity_id, packet_id = self.setup_packet()
        self.authorize(opportunity_id, packet_id)
        with self.assertRaises(StateError):
            self.store.mark_applied(packet_id, "candidate-v2", confirmation_type="user_confirmation", evidence="test")
        path = private_path(self.store.get_packet(packet_id)["artifacts"]["resume_md"]["path"])
        path.write_text("tampered", encoding="utf-8")
        with self.assertRaises(StateError): self.send_fixture(packet_id)
        self.assertEqual(self.store.funnel()["stages"]["applied"], 0)

    def test_suggested_shortlist_is_not_human_shortlist_or_approval(self):
        _, packet_id = self.setup_packet()
        with self.assertRaises(StateError): self.store.approve(packet_id, "candidate-v1", actor="test-user")
        with self.assertRaises(StateError): self.send_fixture(packet_id)

    def test_approval_is_not_sent_and_evidence_is_required(self):
        opportunity_id, packet_id = self.setup_packet()
        self.authorize(opportunity_id, packet_id)
        self.assertEqual(self.store.funnel()["stages"]["applied"], 0)
        with self.assertRaises(StateError): self.store.mark_applied(packet_id, "candidate-v1", confirmation_type="user_confirmation", evidence=" ")
        with self.assertRaises(StateError): self.store.mark_applied(packet_id, "candidate-v1", confirmation_type="approval", evidence="test")
        first = self.send_fixture(packet_id)
        self.assertEqual(first, self.send_fixture(packet_id))

    def test_official_platform_unknowns_require_explicit_risk_acceptance(self):
        unknowns = [{"category": "availability", "status": "unknown", "reason": "每周出勤天数待沟通"}]
        opportunity_id, packet_id = self.setup_packet(observation(official_url="", verification_status="official_platform_live"), assessment(decision="hold", unknown_required=unknowns))
        self.store.human_decision(opportunity_id, "candidate-v1", "shortlist", actor="test-user")
        with self.assertRaises(StateError): self.store.approve(packet_id, "candidate-v1", actor="test-user")
        with self.assertRaises(StateError): self.store.approve(packet_id, "candidate-v1", actor="test-user", accept_unknowns=True)
        approval_id = self.store.approve(packet_id, "candidate-v1", actor="test-user", accept_unknowns=True, review_note="知道平台尚不等于雇主核验；未知出勤将在面试沟通，不填写虚假表单")
        approval = self.store.conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        self.assertEqual(json.loads(approval["unknowns_json"]), unknowns)
        self.assertEqual(self.store.get_opportunity(opportunity_id)["observation"]["verification_status"], "official_platform_live")
        self.send_fixture(packet_id)

    def test_risk_acceptance_cannot_bypass_hard_conflict_failed_or_missing_jd(self):
        cases = [(observation(), assessment(decision="reject", hard_conflicts=[{"reason": "明确必须研究生"}])),
                 (observation(verification_status="failed"), assessment(decision="hold")),
                 (observation(verification_status="closed"), assessment(decision="reject")),
                 (observation(jd_raw=""), assessment(decision="hold")),
                 (observation(official_url="", source_url=""), assessment(decision="hold"))]
        for index, (obs, result) in enumerate(cases):
            obs["external_id"] = str(index); obs["official_url"] = obs["official_url"] + str(index) if obs["official_url"] else ""
            obs["source_url"] = obs["source_url"] + str(index) if obs["source_url"] else ""
            opportunity_id, packet_id = self.setup_packet(obs, result)
            self.store.human_decision(opportunity_id, "candidate-v1", "shortlist", actor="test-user")
            with self.assertRaises(StateError): self.store.approve(packet_id, "candidate-v1", actor="test-user", accept_unknowns=True, review_note="不能覆盖明确事实")

    def test_human_hold_and_re_shortlist_require_new_approval(self):
        opportunity_id, packet_id = self.setup_packet()
        old = self.authorize(opportunity_id, packet_id)
        self.store.human_decision(opportunity_id, "candidate-v1", "hold", actor="test-user")
        with self.assertRaises(StateError): self.send_fixture(packet_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute("INSERT INTO applications(opportunity_id,packet_id,approval_id,confirmation_type,evidence,sent_at,created_at) VALUES(?,?,?,'user_confirmation','test','test','test')", (opportunity_id, packet_id, old))
        self.store.human_decision(opportunity_id, "candidate-v1", "shortlist", actor="test-user")
        with self.assertRaises(StateError): self.send_fixture(packet_id)
        new = self.store.approve(packet_id, "candidate-v1", actor="test-user")
        self.assertNotEqual(old, new)
        self.assertEqual(new, self.store.approve(packet_id, "candidate-v1", actor="test-user"))
        self.send_fixture(packet_id)

    def test_pre_application_contact_is_retained_and_not_counted_as_reply_rate(self):
        opportunity_id, packet_id = self.setup_packet()
        contact = {"name": "测试HR", "role": "hr", "channel": "manual", "address": "fixture"}
        a = self.store.record_interaction(opportunity_id, "hr_reply", "线下索要简历", contact=contact, next_action="核实岗位", due_at="2026-10-01")
        b = self.store.record_interaction(opportunity_id, "hr_reply", "线下索要简历", contact=contact, next_action="核实岗位", due_at="2026-10-01")
        self.assertEqual(a, b)
        self.assertEqual(self.store.funnel()["pre_application_interactions"], 1)
        self.assertEqual(self.store.funnel()["stages"]["effective_replies"], 0)
        self.authorize(opportunity_id, packet_id); self.send_fixture(packet_id)
        self.assertEqual(self.store.funnel()["reply_rate"], 0)
        self.assertIsNone(self.store.get_opportunity(opportunity_id)["interactions"][0]["application_id"])

    def test_interview_then_rejection_preserves_historical_funnel(self):
        opportunity_id, packet_id = self.setup_packet()
        self.authorize(opportunity_id, packet_id); self.send_fixture(packet_id)
        for kind in ("hr_reply", "hiring_manager_reply", "interview", "rejected"):
            self.store.record_interaction(opportunity_id, kind, "fixture " + kind)
        self.store.record_interaction(opportunity_id, "interview", "fixture interview")
        funnel = self.store.funnel()
        self.assertEqual(funnel["stages"]["interview"], 1)
        self.assertEqual(funnel["stages"]["rejected"], 1)
        self.assertEqual(funnel["reply_rate"], 1)
        self.assertEqual(self.store.get_opportunity(opportunity_id)["status"], "rejected")
        self.assertEqual(len(self.store.get_opportunity(opportunity_id)["interactions"]), 4)

    def test_legacy_migration_is_readonly_idempotent_and_does_not_invent_sending(self):
        legacy = self.root / "legacy.sqlite3"
        with sqlite3.connect(legacy) as conn:
            conn.executescript("CREATE TABLE jobs(id INTEGER PRIMARY KEY,provider TEXT,external_id TEXT,title TEXT,company TEXT,description TEXT,created_at TEXT,status TEXT); CREATE TABLE events(id INTEGER PRIMARY KEY,job_id INTEGER,event_type TEXT,detail_json TEXT,created_at TEXT); CREATE TABLE resume_versions(id INTEGER PRIMARY KEY,content TEXT,source_path TEXT,sha256 TEXT);")
            conn.execute("INSERT INTO jobs VALUES(1,'old','42','旧线索','旧公司','','2026-07-15','approved')")
            conn.execute("INSERT INTO events VALUES(1,1,'original_event','{}','2026-07-15')")
            conn.execute("INSERT INTO resume_versions VALUES(1,'原简历内容','old.md','oldhash')")
        conn.close()
        before = hashlib.sha256(legacy.read_bytes()).hexdigest()
        first = self.store.migrate_legacy(legacy)
        second = self.store.migrate_legacy(legacy)
        self.assertEqual(first["new_legacy_records"], 3)
        self.assertEqual(second["new_legacy_records"], 0)
        self.assertEqual(before, hashlib.sha256(legacy.read_bytes()).hexdigest())
        self.assertEqual(self.store.funnel()["stages"]["applied"], 0)
        saved = self.store.conn.execute("SELECT payload_json FROM legacy_records WHERE table_name='resume_versions'").fetchone()[0]
        self.assertEqual(json.loads(saved)["content"], "原简历内容")
        self.assertFalse(self.store.conn.execute("PRAGMA foreign_key_check").fetchall())

    def test_assessment_replay_preserves_human_state_and_new_reject_is_explicit(self):
        opportunity_id, packet_id = self.setup_packet()
        self.authorize(opportunity_id, packet_id)
        prior = self.store.get_opportunity(opportunity_id)["status"]
        self.store.save_assessment(opportunity_id, "candidate-v1", assessment())
        self.assertEqual(self.store.get_opportunity(opportunity_id)["status"], prior)
        self.store.save_assessment(opportunity_id, "candidate-v1", assessment(decision="reject", hard_conflicts=[{"reason": "新明确硬冲突"}]))
        self.assertEqual(self.store.get_opportunity(opportunity_id)["status"], "suggested_reject")
        with self.assertRaises(StateError): self.send_fixture(packet_id)

    def test_assessment_replay_reconciles_only_old_machine_labels(self):
        opportunity_id = self.store.ingest_observation(observation())["opportunity_id"]
        rejected = assessment(decision="reject", hard_conflicts=[{"reason": "明确硬冲突"}])
        first = self.store.save_assessment(opportunity_id, "candidate-v1", rejected)
        with self.store.conn:
            self.store.conn.execute("UPDATE opportunities SET status='hold' WHERE id=?", (opportunity_id,))
        replay = self.store.save_assessment(opportunity_id, "candidate-v1", rejected)
        self.assertEqual(first, replay)
        self.assertEqual(self.store.get_opportunity(opportunity_id)["status"], "suggested_reject")
        self.store.human_decision(opportunity_id, "candidate-v1", "hold", actor="test-user")
        self.store.save_assessment(opportunity_id, "candidate-v1", rejected)
        self.assertEqual(self.store.get_opportunity(opportunity_id)["status"], "hold")


if __name__ == "__main__":
    unittest.main()
