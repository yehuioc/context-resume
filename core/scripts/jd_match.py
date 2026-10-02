# -*- coding: utf-8 -*-
"""
jd-match.py — JD 三因子匹配(依据 core/methods/jd-tailoring.md)
权重: keyword_match 0.55 / skills_coverage 0.25 / section_completeness 0.20
纯本地实现,无 LLM 依赖。
用法:
  python jd-match.py --jd <jd_text_file> [--resume <resume_text_file>] [--skills <skills_json>]
  python jd-match.py --jd <jd_text_file> --profile <candidate-profile.json> [--resume <resume_text_file>]
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 技术词表(中英混合,覆盖 AI 应用/工作流/自动化方向;可按需扩展)
TECH_TERMS = [
    "python", "powerShell", "sql", "git", "docker", "linux", "javascript", "typescript",
    "api", "rest", "openapi", "cli", "json", "yaml", "markdown", "regex",
    "ai", "llm", "agent", "rag", "prompt", "embedding", "vector", "finetune", "fine-tuning",
    "codex", "claude", "deepseek", "gpt", "openai", "gemini",
    "workflow", "automation", "rpa", "n8n", "dify", "coze", "mcp", "tool calling",
    "telegram", "feishu", "wechat", "slack", "bot",
    "sqlite", "redis", "mysql", "postgresql", "mongo",
    "fastapi", "flask", "django", "node", "playwright", "selenium", "ffmpeg",
    "testing", "unit test", "pytest", "ci", "cd", "devops", "github actions",
    "asr", "transcription", "ocr", "playwright",
    "excel", "table", "dashboard", "report", "data", "analytics",
]
SECTION_MARKERS = {
    "education": ["教育", "education", "学校", "本科", "大学"],
    "projects": ["项目", "project", "经历"],
    "skills": ["技能", "skill", "工具", "技术栈"],
    "contact": ["电话", "手机", "邮箱", "email", "微信", "phone", "github"],
}


def extract_jd_terms(jd_text: str) -> list:
    """从 JD 文本抽取技术术语(词表命中 + 上下文判定)。"""
    low = jd_text.lower()
    hits = []
    for term in TECH_TERMS:
        # 词边界匹配(英文按单词,中文直接包含)
        if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", low) or term in low:
            hits.append(term)
    return sorted(set(hits))


def keyword_match(jd_terms: list, resume_text: str) -> float:
    """关键词匹配率:JD 术语在简历文本中的命中比例。"""
    if not jd_terms:
        return 1.0
    low = resume_text.lower()
    hit = sum(1 for t in jd_terms if t in low)
    return hit / len(jd_terms)


def skills_coverage(jd_terms: list, candidate_skills: list) -> float:
    """技能覆盖:JD 术语与候选技能清单的重叠比例。"""
    if not jd_terms:
        return 1.0
    cand = set(s.lower() for s in candidate_skills)
    jd_set = set(jd_terms)
    # 词表术语与技能清单的简单匹配(技能清单含短语时做包含判定)
    covered = 0
    for t in jd_set:
        if t in cand or any(t in c for c in cand):
            covered += 1
    return covered / len(jd_set)


def section_completeness(resume_text: str) -> float:
    """章节完整性:必需章节存在比例(教育/项目/技能/联系)。"""
    low = resume_text.lower()
    present = sum(1 for markers in SECTION_MARKERS.values() if any(m in low for m in markers))
    return present / len(SECTION_MARKERS)


def match(jd_text: str, resume_text: str = "", candidate_skills: list = None) -> dict:
    candidate_skills = candidate_skills or []
    jd_terms = extract_jd_terms(jd_text)
    kw = keyword_match(jd_terms, resume_text) * 0.55
    sc = skills_coverage(jd_terms, candidate_skills) * 0.25
    sec = section_completeness(resume_text) * 0.20
    total = kw + sc + sec
    gaps = [t for t in jd_terms if candidate_skills and not any(t in s.lower() for s in candidate_skills)]
    return {
        "total_score": round(total * 100, 1),
        "dimensions": {
            "keyword_match": round(keyword_match(jd_terms, resume_text), 3),
            "skills_coverage": round(skills_coverage(jd_terms, candidate_skills), 3),
            "section_completeness": round(section_completeness(resume_text), 3),
        },
        "weights": {"keyword_match": 0.55, "skills_coverage": 0.25, "section_completeness": 0.20},
        "jd_terms_found": jd_terms,
        "skill_gaps": gaps,
        "verdict": "strong" if total * 100 >= 75 else "good" if total * 100 >= 60 else "moderate" if total * 100 >= 45 else "weak",
    }


def load_profile_skills(profile_path: str) -> list:
    """从 candidate-profile.json 提取技能(projects 的 role_owned 与 narrative.superpowers 兜底)。"""
    data = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    skills = []
    narr = data.get("narrative", {})
    skills.extend(narr.get("superpowers", []))
    for p in data.get("projects", {}).get("tiers", []):
        skills.append(p.get("name", ""))
        skills.append(p.get("role_owned", ""))
    return [s for s in skills if s]


def main():
    ap = argparse.ArgumentParser(description="JD 三因子匹配")
    ap.add_argument("--jd", required=True, help="JD 文本文件路径")
    ap.add_argument("--resume", default="", help="简历/材料文本文件路径(可选)")
    ap.add_argument("--profile", default="", help="candidate-profile.json 路径(可选,提取技能)")
    ap.add_argument("--skills", default="", help="逗号分隔技能清单(可选,优先于 --profile)")
    args = ap.parse_args()
    jd_text = Path(args.jd).read_text(encoding="utf-8")
    resume_text = Path(args.resume).read_text(encoding="utf-8") if args.resume and Path(args.resume).exists() else ""
    skills = [s.strip() for s in args.skills.split(",") if s.strip()] if args.skills else []
    if not skills and args.profile:
        skills = load_profile_skills(args.profile)
    result = match(jd_text, resume_text, skills)
    result["purpose"] = "文本术语覆盖辅助，不是岗位适配结论；正式要求与事实证据匹配使用 career"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
