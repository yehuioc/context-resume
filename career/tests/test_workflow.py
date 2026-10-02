import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from career_ops.config import private_path
from unittest.mock import patch

from career_ops.cli import main, validate_collection_evidence
from career_ops.review import render_review
from career_ops.store import PROJECT_ROOT, REQUIRED_ARTIFACTS, StateError, Store
from career_ops.workflow import Workflow
from test_store import TMP_ROOT, assessment, observation


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TMP_ROOT)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "state.sqlite3")
        self.workflow = Workflow(self.store)
        self.opportunity_id = self.store.ingest_observation(observation())["opportunity_id"]

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_prepare_replays_same_packet_and_refuses_modified_files(self):
        def build(obs, candidate, result, output_dir):
            files = {}
            for name in REQUIRED_ARTIFACTS:
                path = output_dir / (name + ".txt")
                path.write_text("workflow fixture " + name, encoding="utf-8")
                files[name] = str(path)
            return {"status": "review_ready", "candidate_hash": candidate["candidate_hash"], "jd_hash": obs["jd_hash"], "files": files}
        with patch.object(self.workflow, "candidate", return_value={"candidate_hash": "fixture-candidate"}), patch("career_ops.matching.assess", return_value=assessment()), patch("career_ops.materials.build_packet", side_effect=build) as builder:
            first = self.workflow.prepare(self.opportunity_id, output_root=self.root / "packets")
            second = self.workflow.prepare(self.opportunity_id, output_root=self.root / "packets")
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(builder.call_count, 1)
            private_path(first["artifacts"]["resume_md"]["path"]).write_text("edited", encoding="utf-8")
            with self.assertRaises(StateError): self.workflow.prepare(self.opportunity_id, output_root=self.root / "packets")

    def test_review_escapes_external_markup_and_has_platform_label(self):
        oid = self.store.ingest_observation(observation(external_id="xss", official_url="", verification_status="official_platform_live", jd_raw='<script>alert(1)</script><img src=x onerror="steal()">', role_title="<b>职位</b>"))["opportunity_id"]
        path = render_review(self.store.get_opportunity(oid), None, self.root / "review.html")
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("<script>alert(1)</script>", text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertIn("官方平台岗位入口", text)
        self.assertIn("form-action 'none'", text)

    def test_collection_receipt_rejects_missing_or_tampered_raw_evidence(self):
        source_dir = self.root / "sources"; source_dir.mkdir()
        raw = source_dir / "fixture.raw"; raw.write_bytes(b"source fixture")
        metadata_path = source_dir / "fixture.json"
        evidence = {"raw_path": str(raw), "metadata_path": str(metadata_path), "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(), "requested_url": "https://jobs.example.org/42"}
        metadata_path.write_text(json.dumps(evidence), encoding="utf-8")
        with patch("career_ops.sources.validate_collected_observation"):
            validate_collection_evidence([{"verification_evidence": {"detail": evidence}}], source_dir)
        raw.write_bytes(b"tampered")
        with self.assertRaises(StateError): validate_collection_evidence([{"verification_evidence": {"detail": evidence}}], source_dir)

    def test_cli_no_automatic_send_command(self):
        from career_ops.cli import parser
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit): parser().parse_args(["send"])
        # The real CLI writes only an isolated state fixture.
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(["--db", str(self.root / "cli.sqlite3"), "status"])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(output.getvalue())["send_enabled"])


if __name__ == "__main__":
    unittest.main()
