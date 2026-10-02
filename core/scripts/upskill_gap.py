# -*- coding: utf-8 -*-
"""
upskill-gap.py — 技能缺口统计(依据 core/methods/upskill-gap.md)
从 tracker 归档的 JD 文本统计术语频率 → 与候选技能差集 → 按频率排序缺口清单。
纯本地,无 LLM。
用法:
  python upskill-gap.py --tracker <tracker.json> [--profile <candidate-profile.json>] [--skills "python,sql"]
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jd_match import TECH_TERMS  # 复用词表


def collect_jd_texts(tracker_data: dict) -> list:
    """读取历史导出文件；不创建或修改 tracker。"""
    texts = []
    for app in tracker_data.get("applications", []):
        p = app.get("jd_text_path", "")
        if p and Path(p).exists():
            texts.append(Path(p).read_text(encoding="utf-8"))
    return texts


def collect_career_texts(database: str | Path) -> list[str]:
    """只读当前岗位版本，避免把被替代的 JD 重复计入学习建议。"""
    path = Path(database).resolve()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT r.payload_json FROM opportunities o JOIN jd_revisions r ON r.id=o.current_revision_id")
        return [value for row in rows if (value := str(json.loads(row[0]).get("jd_raw", "")).strip())]


def term_frequency(jd_texts: list) -> Counter:
    freq = Counter()
    for text in jd_texts:
        low = text.lower()
        for term in TECH_TERMS:
            if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", low) or term in low:
                freq[term] += 1
    return freq


def candidate_skills(profile_path: str, cli_skills: str) -> list:
    if cli_skills:
        return [s.strip() for s in cli_skills.split(",") if s.strip()]
    if profile_path and Path(profile_path).exists():
        data = json.loads(Path(profile_path).read_text(encoding="utf-8"))
        if data.get("schema_version") == "career-profile-v1":
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            from career_ops.candidate import load_candidate
            reviewed = load_candidate(profile_path)
            return [alias for capability in reviewed.get("capabilities", [])
                    if capability.get("status") == "direct" for alias in capability.get("aliases", [])]
        skills = []
        for p in data.get("projects", {}).get("tiers", []):
            skills.append(p.get("name", ""))
            skills.append(p.get("role_owned", ""))
        return [s for s in skills if s]
    return []


def gap_analysis(freq: Counter, skills: list, total_jds: int) -> list:
    """缺口清单:JD 要求但候选技能未覆盖的术语,按频率排序。"""
    cand = set(s.lower() for s in skills)
    gaps = []
    for term, count in freq.most_common():
        covered = term in cand or any(term in c for c in cand)
        if not covered:
            gaps.append({
                "term": term,
                "jd_mentions": count,
                "coverage_ratio": round(count / total_jds, 3) if total_jds else 0,
                "priority": "high" if count / max(total_jds, 1) >= 0.5 else "medium" if count / max(total_jds, 1) >= 0.25 else "low",
            })
    return gaps


def main():
    ap = argparse.ArgumentParser(description="术语频率与学习建议；不构成能力判定")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--tracker", help="历史 tracker.json，只读")
    source.add_argument("--career-export", help="career 的只读导出 JSON")
    source.add_argument("--db", default=str(Path(__file__).resolve().parents[2] / "career/private/career-ops.sqlite3"))
    ap.add_argument("--profile", default="", help="candidate-profile.json 路径(提取技能)")
    ap.add_argument("--skills", default="", help="逗号分隔技能清单(优先于 --profile)")
    args = ap.parse_args()
    if args.tracker:
        jd_texts = collect_jd_texts(json.loads(Path(args.tracker).read_text(encoding="utf-8")))
    elif args.career_export:
        export = json.loads(Path(args.career_export).read_text(encoding="utf-8"))
        if export.get("schema") != "career-ops-readonly-v1" or export.get("writable") is not False:
            sys.exit("需要 career-ops-readonly-v1 只读导出")
        jd_texts = [str(item.get("jd_raw", "")) for item in export.get("opportunities", []) if item.get("jd_raw")]
    else:
        jd_texts = collect_career_texts(args.db)
    if not jd_texts:
        sys.exit("no JD text files found (tracker jd_text_path 均缺失或不存在)")
    freq = term_frequency(jd_texts)
    skills = candidate_skills(args.profile, args.skills)
    gaps = gap_analysis(freq, skills, len(jd_texts))
    result = {
        "purpose": "术语学习建议；能力是否满足由 career 的审核事实和证据匹配决定",
        "total_jds": len(jd_texts),
        "candidate_skills": skills,
        "top_terms": freq.most_common(15),
        "gaps": gaps,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
