# -*- coding: utf-8 -*-
"""jd-match.py smoke tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jd_match


class TestJdMatch(unittest.TestCase):
    JD = "招聘 AI 实习生:要求 python、api、automation、workflow、prompt 经验,熟悉 sqlite"
    RESUME = "教育:本科。项目:构建 Telegram bot 自动化 workflow,使用 python 与 sqlite,调用 api。"

    def test_keyword_match(self):
        terms = jd_match.extract_jd_terms(self.JD)
        self.assertIn("python", terms)
        self.assertIn("sqlite", terms)
        kw = jd_match.keyword_match(terms, self.RESUME)
        self.assertGreater(kw, 0.5)

    def test_skills_coverage(self):
        terms = jd_match.extract_jd_terms(self.JD)
        cov = jd_match.skills_coverage(terms, ["python", "sqlite", "api"])
        self.assertGreaterEqual(cov, 0.5)

    def test_section_completeness(self):
        # RESUME 只含教育/项目两章(无技能/联系方式)→ 0.5
        self.assertEqual(jd_match.section_completeness(self.RESUME), 0.5)
        self.assertEqual(jd_match.section_completeness("只有一句话"), 0.0)

    def test_match_weights(self):
        r = jd_match.match(self.JD, self.RESUME, ["python", "sqlite", "api"])
        self.assertEqual(r["weights"]["keyword_match"], 0.55)
        self.assertLessEqual(r["total_score"], 100)
        self.assertGreaterEqual(r["total_score"], 0)

    def test_skill_gaps(self):
        r = jd_match.match(self.JD, self.RESUME, ["python"])
        self.assertIn("sqlite", r["skill_gaps"])


if __name__ == "__main__":
    unittest.main()
