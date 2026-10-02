import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from career_ops import sources


LIVE_HTML = '''<html><body><li id="jobName">AI应用实习生</li><div class="site-tag">广东省深圳市</div><div class="apply"><a>投递简历</a></div><div class="modal hidden">职位已下线</div><pre class="mainContent">岗位职责：
1. 用 Python 实现 Agent 自动化。

任职要求：
1. 在校本科生，每周4天。

加分项：
1. 有公开项目证据。</pre><script>职位已下线; steal_credentials()</script></body></html>'''


def ncss_obs():
    return sources._observation(company="测试公司", role_title="AI应用实习生", source_channel="ncss", source_url="https://www.ncss.cn/student/jobs/abc/detail.html", external_id="abc", jd_raw="old JD")


class SourcesTests(unittest.TestCase):
    def test_html_entities_paragraphs_and_script_excluded(self):
        content = '&lt;h2&gt;Requirements&lt;/h2&gt;&lt;p&gt;Python required&lt;/p&gt;&lt;script&gt;steal()&lt;/script&gt;&lt;h2&gt;Nice to have&lt;/h2&gt;&lt;ul&gt;&lt;li&gt;Agent experience&lt;/li&gt;&lt;/ul&gt;'
        text = sources.extract_html(content)
        self.assertIn("Requirements\n\nPython required", text)
        self.assertNotIn("steal", text)
        sections = sources.split_jd_sections(text)
        self.assertIn("Python", sections["required"])
        self.assertIn("Agent", sections["preferred"])

    def test_platform_live_is_not_employer_verified(self):
        with patch.object(sources, "_fetch", return_value=(LIVE_HTML, {"http_status": 200})):
            result = sources.verify_observation(ncss_obs())
        self.assertEqual(result["verification_status"], "official_platform_live")
        self.assertEqual(result["official_url"], "")
        self.assertTrue(result["source_verified"])
        self.assertFalse(result["application_verified"])
        self.assertEqual(result["employment_type"], "internship")
        self.assertIn("广东省深圳市", result["location"])
        self.assertNotIn("steal_credentials", result["jd_raw"])
        self.assertEqual(result["jd_hash"], hashlib.sha256(result["jd_raw"].encode()).hexdigest())

    def test_http_200_without_detail_never_means_open(self):
        with patch.object(sources, "_fetch", return_value=("<html>请登录</html>", {})):
            result = sources.verify_observation(ncss_obs())
        self.assertEqual(result["verification_status"], "unknown")
        self.assertEqual(result["jd_raw"], "old JD")

    def test_hidden_or_disabled_application_block_is_not_live(self):
        for klass in ["apply hidden", "apply disabled"]:
            with self.subTest(klass=klass), patch.object(sources, "_fetch", return_value=(LIVE_HTML.replace('class="apply"', 'class="' + klass + '"'), {})):
                self.assertEqual(sources.verify_observation(ncss_obs())["verification_status"], "unknown")

    def test_company_identity_change_is_not_live(self):
        page = LIVE_HTML.replace("</body>", '<span id="realCorpName">另一家公司</span></body>')
        with patch.object(sources, "_fetch", return_value=(page, {})):
            result = sources.verify_observation(ncss_obs())
        self.assertEqual(result["verification_status"], "unknown")
        self.assertIn("source_identity_changed", result["risk_flags"])

    def test_visible_close_marker_wins_over_apply_button(self):
        with patch.object(sources, "_fetch", return_value=(LIVE_HTML.replace('<div class="modal hidden">', '<div>'), {})):
            result = sources.verify_observation(ncss_obs())
        self.assertEqual(result["verification_status"], "closed")
        self.assertFalse(result["source_verified"])

    def test_network_failure_preserves_jd_and_does_not_close(self):
        with patch.object(sources, "_fetch", side_effect=sources.SourceError("timeout")):
            result = sources.verify_observation(ncss_obs())
        self.assertEqual(result["verification_status"], "failed")
        self.assertEqual(result["jd_raw"], "old JD")
        self.assertNotIn("closed", result["risk_flags"])

    def test_trusted_http_404_is_closed(self):
        problem = sources.SourceError("HTTP 404")
        problem.__cause__ = HTTPError("https://www.ncss.cn", 404, "gone", {}, None)
        with patch.object(sources, "_fetch", side_effect=problem):
            self.assertEqual(sources.verify_observation(ncss_obs())["verification_status"], "closed")

    def test_identity_mismatch_cannot_fetch(self):
        obs = ncss_obs(); obs["source_url"] = "https://localhost/credentials"
        with patch.object(sources, "_fetch") as fetch:
            result = sources.verify_observation(obs)
        fetch.assert_not_called()
        self.assertEqual(result["verification_status"], "failed")

    def test_manual_claim_is_unverified_and_script_is_sanitized(self):
        result = sources.import_manual({"company": "Company", "title": "Engineer", "jd_raw": "<p>Python</p><script>run()</script>", "verification_status": "employer_verified", "official_url": "https://example.com"})
        self.assertEqual(result["verification_status"], "unknown")
        self.assertEqual(result["official_url"], "")
        self.assertEqual(result["jd_raw"], "Python")
        with patch.object(sources, "_fetch") as fetch:
            self.assertEqual(sources.verify_observation(result)["verification_status"], "unknown")
        fetch.assert_not_called()

    def test_ssrf_urls_rejected(self):
        for url in ["file:///E:/secret", "http://localhost/", "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "https://user:password@example.com", "https://example.com:9000", "https://internal.local/", "https://2130706433/"]:
            with self.subTest(url=url), self.assertRaises(sources.SourceError):
                sources.validate_public_url(url)
        with patch.object(sources.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(sources.SourceError):
                sources.validate_public_url("https://example.com", resolve=True)

    def test_greenhouse_origin_is_exact_employer_link(self):
        item = {"id": 123, "title": "Product Engineer", "absolute_url": "https://boards.greenhouse.io/anthropic/jobs/123", "content": "&lt;p&gt;Required: Python&lt;/p&gt;", "location": {"name": "Remote-Friendly, United States"}}
        canonical = "https://job-boards.greenhouse.io/anthropic/jobs/123"
        verified = sources._greenhouse_observation(item, "anthropic", {}, {canonical}, {"employer_careers": {"http_status": 200}})
        unknown = sources._greenhouse_observation(item, "anthropic", {}, set(), {})
        self.assertEqual(verified["verification_status"], "employer_verified")
        self.assertEqual(verified["official_url"], canonical)
        self.assertEqual(verified["work_mode"], "hybrid")
        self.assertEqual(unknown["verification_status"], "unknown")
        self.assertEqual(unknown["official_url"], "")

    def test_ncss_pagination_dedup_and_explicit_schema_failure(self):
        def listing(url, *args):
            page = "offset=1" in url
            items = [{"jobId": "abc", "jobName": "AI应用实习生", "recName": "测试公司"}]
            return {"flag": True, "errors": [], "data": {"list": items if page else []}}, {"requested_url": url}
        with patch.object(sources, "_json_fetch", side_effect=listing), patch.object(sources, "_fetch", return_value=(LIVE_HTML, {})):
            result = sources.collect_ncss("AI", limit=1)
        self.assertEqual(len(result), 1)
        with patch.object(sources, "_json_fetch", return_value=({"flag": False}, {})), self.assertRaises(sources.SourceError):
            sources.collect_ncss("AI")

    def test_nonintern_is_not_default_graduate(self):
        self.assertEqual(sources._employment_type("AI开发工程师", "Python"), "unknown")
        self.assertEqual(sources._work_mode("武汉", "不接收线上实习生"), "on_site")

    def test_cross_host_redirect_is_rejected(self):
        with patch.object(sources, "_network_url", side_effect=lambda url: url):
            req = sources.request.Request("https://www.ncss.cn/student/jobs/abc/detail.html")
            with self.assertRaises(sources.SourceError):
                sources._SafeRedirect().redirect_request(req, None, 302, "moved", {}, "https://anthropic.com/careers")

    def test_evidence_path_cannot_escape_project(self):
        with self.assertRaises(sources.SourceError):
            sources._save_response(b"{}", {}, Path("E:/outside-career-ops"))

    def test_invalid_json_fails_explicitly(self):
        with patch.object(sources, "_fetch", return_value=("<html>blocked</html>", {})), self.assertRaises(sources.SourceError):
            sources._json_fetch("https://www.ncss.cn", 10, None)

    def test_collected_ncss_semantics_and_derived_fields(self):
        parent = sources.PROJECT_PRIVATE / "tests"; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            def save(text, url):
                return sources._save_response(text.encode(), {"requested_url": url, "final_url": url, "http_status": 200}, directory)
            list_url = sources.NCSS_API + "?jobName=AI&offset=1&limit=20&sourcesName=0"
            listing = save(json.dumps({"data": {"list": [{"jobId": "abc", "jobName": "AI应用实习生", "recName": "测试公司"}]}}), list_url)
            detail = save(LIVE_HTML, ncss_obs()["source_url"])
            with patch.object(sources, "_fetch", return_value=(LIVE_HTML, detail)):
                observation = sources.verify_observation(ncss_obs())
            observation["verification_evidence"]["listing"] = listing
            sources.validate_collected_observation(observation)
            for key, changed in [("role_title", "Fake senior job"), ("company", "different employer"), ("employment_type", "graduate"), ("verification_status", "employer_verified"), ("jd_raw", "Fake JD")]:
                altered = dict(observation); altered[key] = changed
                if key == "jd_raw": altered["jd_hash"] = sources.jd_hash(changed)
                with self.subTest(key=key), self.assertRaises(sources.SourceError):
                    sources.validate_collected_observation(altered)

    def test_collected_greenhouse_requires_exact_official_link(self):
        parent = sources.PROJECT_PRIVATE / "tests"; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            def save(text, url):
                return sources._save_response(text.encode(), {"requested_url": url, "final_url": url, "http_status": 200}, directory)
            item = {"id": 123, "title": "Product Engineer", "absolute_url": "https://boards.greenhouse.io/anthropic/jobs/123", "content": "&lt;p&gt;Python required&lt;/p&gt;", "location": {"name": "London, UK"}}
            canonical = "https://job-boards.greenhouse.io/anthropic/jobs/123"
            ats = save(json.dumps(item), sources.GREENHOUSE_API + "anthropic/jobs/123")
            origin = save('<a href="' + canonical + '">Apply</a>', sources.OFFICIAL_BOARDS["anthropic"]["careers"])
            obs = sources._greenhouse_observation(item, "anthropic", ats, {canonical}, {"employer_careers": origin})
            sources.validate_collected_observation(obs)
            obs["verification_evidence"]["employer_origin"]["employer_careers"] = save('<a href="https://job-boards.greenhouse.io/anthropic/jobs/999">Different job</a>', sources.OFFICIAL_BOARDS["anthropic"]["careers"])
            with self.assertRaises(sources.SourceError):
                sources.validate_collected_observation(obs)

    def test_oss_retry_preserves_pin_and_reviewed_metadata(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "research_oss.py"
        spec = importlib.util.spec_from_file_location("career_research_oss", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        pinned = {"url": "https://github.com/owner/repo", "repository": "owner/repo", "resolved_repository": "owner/newname", "commit": "a" * 40,
                  "license": "MIT", "default_branch": "main", "reviewed_reference_only": True, "review_state": "reviewed"}
        with patch.object(module, "fetch", side_effect=AssertionError("must not read moving HEAD")):
            self.assertEqual(module.metadata(pinned), pinned)
        parent = sources.PROJECT_PRIVATE / "tests"; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory, patch.object(module, "OUT", Path(directory)):
            requested = []
            def fetch(url):
                requested.append(url)
                return json.dumps({"tree": [{"type": "blob", "path": "README.md"}]}).encode() if "/git/trees/" in url else b"Pinned README"
            with patch.object(module, "fetch", side_effect=fetch):
                result = module.snapshot(dict(pinned))
            self.assertTrue(all("a" * 40 in url for url in requested))
            for field in ["commit", "license", "resolved_repository", "reviewed_reference_only", "review_state"]:
                self.assertEqual(result[field], pinned[field])


if __name__ == "__main__":
    unittest.main()
