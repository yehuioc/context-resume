# -*- coding: utf-8 -*-
"""upskill-gap.py smoke tests."""
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import upskill_gap


class TestUpskillGap(unittest.TestCase):
    def test_term_frequency(self):
        texts = ["要求 python 与 api 开发", "python 和 automation", "workflow 设计"]
        freq = upskill_gap.term_frequency(texts)
        self.assertEqual(freq["python"], 2)
        self.assertEqual(freq["api"], 1)

    def test_gap_analysis_priority(self):
        freq = Counter({"python": 8, "sql": 3, "rag": 1})
        gaps = upskill_gap.gap_analysis(freq, ["python"], total_jds=10)
        names = {g["term"]: g for g in gaps}
        self.assertNotIn("python", names)  # 已覆盖
        self.assertEqual(names["sql"]["priority"], "medium")
        self.assertEqual(names["rag"]["priority"], "low")

    def test_collect_jd_texts(self):
        with tempfile.TemporaryDirectory() as d:
            jd = Path(d) / "jd.txt"
            jd.write_text("要求 python", encoding="utf-8")
            tracker_data = {"applications": [{"jd_text_path": str(jd)}, {"jd_text_path": "missing.txt"}]}
            texts = upskill_gap.collect_jd_texts(tracker_data)
            self.assertEqual(len(texts), 1)


if __name__ == "__main__":
    unittest.main()
