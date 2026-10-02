"""采集真实 JD 验收集，不使用旧空正文 leads，也不执行投递。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from career_ops.sources import SourceError, collect_greenhouse, collect_ncss, utc_now, verify_observation
from career_ops.config import private_reference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "private" / "samples.json")
    parser.add_argument("--keywords", nargs="+", default=["AI", "Agent", "实习", "Python", "智能体", "自动化"])
    parser.add_argument("--ncss-per-keyword", type=int, default=30)
    parser.add_argument("--limit", type=int, default=28)
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((PROJECT / "private").resolve()):
        parser.error("output must remain inside career-ops/private")
    if args.limit < 20:
        parser.error("sample acceptance requires at least 20 complete real JD observations")
    evidence_dir = PROJECT / "private" / "sources"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    started = utc_now()
    all_jobs, errors, queries = {}, [], []
    for keyword in args.keywords:
        try:
            jobs = collect_ncss(keyword, limit=args.ncss_per_keyword, max_pages=3, timeout=args.timeout, evidence_dir=evidence_dir)
            queries.append({"provider": "ncss", "keyword": keyword, "returned": len(jobs)})
            for obs in jobs:
                all_jobs[(obs["source_channel"], obs["external_id"])] = obs
            print(f"NCSS {keyword}: {len(jobs)} observations", flush=True)
        except SourceError as exc:
            errors.append({"provider": "ncss", "keyword": keyword, "error": str(exc)})
            print(f"NCSS {keyword}: source failed: {exc}", flush=True)
    overseas = []
    try:
        jobs = collect_greenhouse("anthropic", limit=1000, timeout=args.timeout, evidence_dir=evidence_dir)
        queries.append({"provider": "greenhouse:anthropic", "returned": len(jobs), "pagination": "API returns all jobs; no invented page parameters"})
        for pattern in [r"^Product Engineer, Computer Use", r"^Applied AI Engineer Tokyo", r"^Associate Applied AI", r"^Anthropic Fellows Program, AI Safety"]:
            candidates = [j for j in jobs if re.search(pattern, j["role_title"], re.I)]
            if candidates:
                overseas.append(verify_observation(candidates[0], timeout=args.timeout, evidence_dir=evidence_dir))
        for obs in overseas:
            all_jobs[(obs["source_channel"], obs["external_id"])] = obs
        print(f"Greenhouse: {len(jobs)} published records, {len(overseas)} selected overseas observations", flush=True)
    except SourceError as exc:
        errors.append({"provider": "greenhouse:anthropic", "error": str(exc)})
        print(f"Greenhouse: source failed: {exc}", flush=True)
    complete = [obs for obs in all_jobs.values() if len(obs["jd_raw"]) >= 80]
    domestic = [j for j in complete if j["source_channel"] == "ncss"]
    # Selection serves this user's internship/Agent/application focus; no synthetic jobs.
    def relevance(obs):
        title = obs["role_title"]
        direction = bool(re.search(r"Agent|智能体|AI|产品|自动化|软件|Python|Java|电子|通信|开发|测试", title, re.I))
        intern = obs["employment_type"] == "internship"
        return (obs["verification_status"] == "official_platform_live", direction and intern, direction,
                intern, not bool(re.search(r"算法|标注|客服|销售", title)), obs.get("posted_at") or "")
    domestic.sort(key=relevance, reverse=True)
    # Keep no more than two identical JD bodies in the review sample; the full pool retains all legal entities/IDs.
    domestic_selected, body_counts = [], Counter()
    domestic_limit = max(0, args.limit - len(overseas))
    for obs in domestic:
        if body_counts[obs["jd_hash"]] >= 2:
            continue
        domestic_selected.append(obs)
        body_counts[obs["jd_hash"]] += 1
        if len(domestic_selected) >= domestic_limit:
            break
    selected = domestic_selected + overseas
    # Preserve a real closed/stale domestic negative when observed, without replacing the entire candidate set.
    negative = next((j for j in domestic if j["verification_status"] == "closed" or "stale_posting" in j["risk_flags"]), None)
    if negative and negative not in selected:
        selected.append(negative)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    pool_path = output.with_name("sample-pool.json")
    pool_path.write_text(json.dumps(list(all_jobs.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    receipt = {"producer": "codex", "producer_role": "foreground-worker", "producer_evidence": "native career_sources subagent; scripts/collect_samples.py live public GET collection",
               "review_owner": "codex-controller", "review_state": "needs_review", "canonical_status": "candidate",
               "started_at": started, "finished_at": utc_now(), "commands": "python scripts/collect_samples.py", "source_queries": queries,
               "selected_file": private_reference(output), "selected_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "pool_file": private_reference(pool_path), "evidence_dir": private_reference(evidence_dir),
               "full_jd_selected": sum(len(j["jd_raw"]) >= 80 for j in selected), "source_counts": dict(Counter(j["source_channel"] for j in selected)),
               "verification_counts": dict(Counter(j["verification_status"] for j in selected)), "employment_counts": dict(Counter(j["employment_type"] for j in selected)),
               "failures": errors, "boundary": "NCSS is platform publication, not independent employer identity. Anthropic roles are overseas source/identity constraint negatives; official FAQ currently says no internships. No resume sent, login or installation performed."}
    receipt_path = output.with_name("collection-receipt.json")
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"sample_file": str(output), "full_jd_selected": receipt["full_jd_selected"], "statuses": receipt["verification_counts"], "employment": receipt["employment_counts"], "failures": errors}, ensure_ascii=False), flush=True)
    if receipt["full_jd_selected"] < 20 or not domestic or not overseas:
        raise SystemExit("collection incomplete: needs 20 complete JD records and both domestic and overseas observations; evidence retained")


if __name__ == "__main__":
    main()
