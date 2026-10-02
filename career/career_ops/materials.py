"""Build review-ready application packets using approved sentences only."""
from __future__ import annotations

import difflib
import html
import json
import re
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .candidate import (PROJECT_ROOT, WORKSPACE_ROOT, CandidateError, approved_text,
                        canonical_hash, sha256_bytes, verify_candidate_current)
from .matching import assess, jd_text, job_id, job_title, verify_requirement_offsets

MATERIAL_VERSION = "career-materials-v1"


class MaterialError(ValueError):
    """The packet is stale, unreviewed, or includes a non-approved claim."""


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def _safe_label(value: object, limit: int = 120) -> str:
    """JD labels may identify the target; they never become candidate claims."""
    return re.sub(r"[\r\n\x00-\x1f]", " ", str(value)).strip()[:limit]


def _md(value: str) -> str:
    # Text must remain inert even in a Markdown reader permitting inline HTML.
    value = html.escape(value, quote=False)
    return re.sub(r"([\\`*{}\[\]()#+!|])", r"\\\1", value)


def _url(value: object) -> str | None:
    value = str(value or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    if any(char in value for char in ("\n", "\r", "\x00", '"', "<", ">")):
        return None
    return value


def _provenance(evidence: str) -> str:
    return ("---\nproducer: codex\nproducer_role: foreground-worker\n"
            f"producer_evidence: {json.dumps(evidence, ensure_ascii=False)}\n"
            "review_owner: codex-controller\nreview_state: needs_review\n"
            "canonical_status: candidate\n---\n\n")


def _facts(candidate: dict) -> dict:
    return {fact["id"]: fact for fact in candidate["facts"]}


def _select_facts(candidate: dict, assessment: dict) -> list[str]:
    """Rank reviewed project groups; keep role/education and retrieval boundaries."""
    known = _facts(candidate)
    material = candidate.get("materials", {})
    relevance = {fact_id: 0 for fact_id in known}
    for requirement in assessment["requirements"]:
        for fact_id in requirement.get("fact_ids", []):
            if fact_id in relevance:
                relevance[fact_id] += 3 if requirement["priority"] == "required" else 1
    selected = []
    selected += material.get("intro_fact_ids", [])
    selected += material.get("skill_fact_ids", [])
    projects = material.get("primary_fact_ids", []) or [f["id"] for f in candidate["facts"] if f.get("kind") == "project"]
    # Sort whole projects rather than scattering their individual bullets.
    groups: OrderedDict[str, list[str]] = OrderedDict()
    for fact_id in projects:
        if fact_id in known:
            groups.setdefault(known[fact_id].get("project_id", fact_id), []).append(fact_id)
    sorted_groups = sorted(groups.values(), key=lambda ids: -sum(relevance[i] for i in ids))
    target = " ".join(r["quote"] for r in assessment["requirements"])
    if assessment.get("job_family") == "AI工作流/Agent应用" and not re.search(r"Telegram|日报|SQLite|消息幂等", target, re.I):
        anchors = {"project-brain": 0, "personal-workbench": 1, "daily-bot": 2}
        sorted_groups.sort(key=lambda ids: anchors.get(known[ids[0]].get("project_id"), 3))
    for ids in sorted_groups:
        selected += sorted(ids, key=lambda i: -relevance[i])
    selected += material.get("required_fact_ids", [])
    # These facts are mandatory even when a malformed material preference omits them.
    selected += [f["id"] for f in candidate["facts"] if f.get("kind") in {"education", "role"}]
    return list(dict.fromkeys(i for i in selected if i in known))


def _claim(candidate: dict, fact_id: str, text: str, *, surface: str, position: str) -> dict:
    approved_text(candidate, fact_id, text)
    fact = _facts(candidate)[fact_id]
    return {"text": text, "fact_ids": [fact_id], "surface": surface, "position": position,
            "source_hashes": [fact["source"]["sha256"]], "source_paths": [fact["source"]["path"]],
            "source_locators": [fact["source"]["locator"]], "fact_versions": [fact["version"]],
            "candidate_hash": candidate["candidate_hash"], "claim_type": "approved_fact_sentence"}


def _resume(candidate: dict, job: dict, assessment: dict) -> tuple[str, list[dict], list[dict]]:
    selected = _select_facts(candidate, assessment)
    known = _facts(candidate)
    claims, blocks = [], []
    identity = candidate["identity"]
    material = candidate.get("materials", {})
    headline = material.get("headline") or identity["name"]
    headline_fact = next((f for f in known.values() if f["text"] == headline), None)
    if not headline_fact:
        # The name is a reviewed structured profile field; no invented persona headline.
        headline = identity["name"]
    else:
        claims.append(_claim(candidate, headline_fact["id"], headline, surface="resume", position="headline"))
    target = _safe_label(job_title(job))
    blocks.append({"kind": "title", "text": headline})
    blocks.append({"kind": "target", "text": "应聘岗位：" + target})
    contact = identity.get("contact", {})
    if isinstance(contact, str):
        contact = {"contact": contact}
    contact_text = " ｜ ".join(str(contact[key]) for key in ("phone", "email", "location", "contact") if contact.get(key))
    if contact_text:
        blocks.append({"kind": "contact", "text": contact_text})
    for key, label in (("portfolio", "作品集"), ("github", "GitHub")):
        if _url(contact.get(key)):
            blocks.append({"kind": "link", "text": label + "：" + contact[key], "url": contact[key]})
    sections: OrderedDict[str, list[str]] = OrderedDict()
    sections["个人概述"] = [i for i in selected if i in material.get("intro_fact_ids", [])]
    sections["技能与实践边界"] = [i for i in selected if known[i].get("kind") == "skill"]
    for fact_id in selected:
        fact = known[fact_id]
        if fact.get("kind") == "project":
            sections.setdefault(fact.get("project_name") or "项目实践", []).append(fact_id)
    sections["教育背景"] = [i for i in selected if known[i].get("kind") == "education"]
    sections["本人职责"] = [i for i in selected if known[i].get("kind") == "role" and i not in sections["个人概述"]]
    lines = [_provenance(f"career-ops {MATERIAL_VERSION}；JD {assessment['jd_hash']}；profile {candidate['candidate_hash']}").rstrip(), "", "# " + _md(headline), "", "应聘岗位：" + _md(target), ""]
    if contact_text:
        lines += [_md(contact_text), ""]
    for block in blocks:
        if block["kind"] == "link":
            lines += [_md(block["text"]), ""]
    for heading, ids in sections.items():
        if not ids:
            continue
        lines += ["## " + _md(heading), ""]
        blocks.append({"kind": "heading", "text": heading})
        for fact_id in ids:
            text = approved_text(candidate, fact_id)
            lines += ["- " + _md(text)]
            blocks.append({"kind": "bullet", "text": text, "fact_id": fact_id})
            claims.append(_claim(candidate, fact_id, text, surface="resume", position=heading))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n", claims, blocks


def resume_html(blocks: list[dict]) -> str:
    rendered = []
    for block in blocks:
        text = html.escape(block["text"], quote=True)
        kind = block["kind"]
        if kind == "title":
            rendered.append("<h1>" + text + "</h1>")
        elif kind == "heading":
            rendered.append("<h2>" + text + "</h2>")
        elif kind == "bullet":
            rendered.append('<p class="bullet">• ' + text + "</p>")
        elif kind == "link" and _url(block.get("url")):
            rendered.append('<p class="contact"><a rel="noreferrer" href="' + html.escape(block["url"], quote=True) + '">' + text + "</a></p>")
        else:
            rendered.append('<p class="' + ("target" if kind == "target" else "contact") + '">' + text + "</p>")
    return ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;; img-src &#39;none&#39;">'
            "<title>岗位版简历</title><style>"
            "@page{size:A4;margin:14mm}body{font-family:'Microsoft YaHei','Noto Sans CJK SC',sans-serif;max-width:760px;margin:28px auto;color:#18242e;line-height:1.5;font-size:13px}"
            "h1{font-size:23px;line-height:1.3;margin:0 0 8px}h2{font-size:15px;border-bottom:1px solid #b8c7d1;padding-bottom:3px;margin:17px 0 6px}"
            ".bullet{margin:4px 0}.contact{font-size:11px;margin:2px 0;color:#42586a}.target{font-size:12px;color:#2f5a72;margin:4px 0}a{color:#2f5a72;text-decoration:none}"
            "@media print{body{margin:0;font-size:10.5px}h1{font-size:19px}h2{font-size:12px;margin-top:11px}.contact{font-size:9px}}"
            "</style></head><body>" + "\n".join(rendered) + "</body></html>\n")


def _assessment_md(job: dict, assessment: dict) -> str:
    lines = [_provenance("career-ops local deterministic assessment").rstrip(), "", "# 岗位评估与核验", "",
             f"岗位：{_md(job_title(job))} ｜ 公司：{_md(_safe_label(job.get('company', '待核验')))}", "",
             f"当前建议：`{assessment['decision']}`；资格状态：`{assessment['eligibility_status']}`。", "",
             assessment["scoring_boundary"], "", "## 推荐理由", ""]
    lines += ["- " + _md(reason) for reason in assessment["recommendation_reasons"]]
    lines += ["", "## 风险与待核验", ""]
    items = [item.get("reason", str(item)) for item in assessment["hard_conflicts"] + assessment["unknown_required"] + assessment["explicit_gaps"]]
    items += assessment["risk_notes"]
    lines += ["- " + _md(item) for item in list(dict.fromkeys(items))] or ["- 仍需人工审核材料并确认真实投递；分数不是批准。"]
    lines += ["", "## R/E/U/V 逐项记录", ""]
    for requirement in assessment["requirements"]:
        lines += [f"### {requirement['id']} ｜ {requirement['priority']} ｜ {requirement['status']}", "",
                  f"原文来源：`{requirement.get('source_field', 'jd_raw')}`，字符区间：`[{requirement['start']}, {requirement['end']})`", "",
                  "> " + _md(requirement["quote"]), ""]
        for component in requirement["components"]:
            ids = ", ".join(component["fact_ids"]) or "无审核事实"
            lines.append(f"- `{component['status']}` / `{component['category']}` / `{ids}`：" + _md(component["reason"]))
            if component.get("verification"):
                lines.append("  核验：" + _md(component["verification"]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _outreach(candidate: dict, job: dict) -> tuple[dict[str, str], list[dict]]:
    known = _facts(candidate)
    material = candidate.get("materials", {})
    name = _safe_label(candidate["identity"]["name"])
    title = _safe_label(job_title(job))
    evidence_ids = material.get("evidence_fact_ids", [])[:3]
    intro_ids = material.get("intro_fact_ids", [])[:1]
    role_ids = [i for i in material.get("required_fact_ids", []) if known[i].get("kind") == "role"]
    availability_ids = material.get("availability_fact_ids", [])
    claims = []
    def sentences(ids, surface):
        result = []
        for fact_id in ids:
            text = approved_text(candidate, fact_id)
            claims.append(_claim(candidate, fact_id, text, surface=surface, position="body"))
            result.append(text)
        return result
    intro = sentences(intro_ids, "greeting")
    available = sentences(availability_ids, "greeting")
    role = sentences(role_ids, "greeting")
    greeting = "您好，我是" + name + "，希望应聘贵公司的「" + title + "」。\n\n" + "\n".join(intro + role + available) + "\n\n可以提供与岗位相关的项目证据，期待进一步沟通岗位任务和实际到岗安排。\n"
    email = "主题：应聘「" + title + "」｜" + name + "\n\n" + greeting + "\n相关项目证据：\n"
    for fact_id in intro_ids + role_ids + availability_ids:
        claims.append(_claim(candidate, fact_id, approved_text(candidate, fact_id), surface="email", position="body"))
    for fact_id in evidence_ids:
        text = approved_text(candidate, fact_id)
        email += "- " + text + "\n"
        claims.append(_claim(candidate, fact_id, text, surface="email", position="related_evidence"))
    contact = candidate["identity"].get("contact", {})
    if isinstance(contact, dict):
        email += "\n" + " ｜ ".join(str(contact[k]) for k in ("phone", "email") if contact.get(k)) + "\n"
    # The spoken script is bounded by count, not an unverified promise of speaking speed.
    oral_ids = list(role_ids or intro_ids)
    if evidence_ids:
        # Choose the shortest approved project sentence to keep the oral draft compact.
        project_id = min(evidence_ids, key=lambda i: len(known[i]["text"]))
        oral_ids.append(project_id)
    self_intro = "大家好，我是" + name + "。\n" + "\n".join(sentences(oral_ids, "self_intro")) + "\n"
    self_intro += "希望进一步沟通岗位任务。\n"
    evidence = []
    for fact_id in evidence_ids:
        fact = known[fact_id]
        item = {"fact_id": fact_id, "project_name": fact.get("project_name"), "text": approved_text(candidate, fact_id),
                "source": {k: v for k, v in fact["source"].items() if k != "resolved_path"},
                "version": fact["version"], "evidence_url": _url(fact.get("evidence_url"))}
        evidence.append(item)
        claims.append(_claim(candidate, fact_id, item["text"], surface="evidence", position=str(len(evidence))))
    return {"greeting": greeting, "email": email, "intro": self_intro, "evidence": _json(evidence)}, claims


def verify_claim_audit(candidate: dict, audit: dict) -> None:
    if audit.get("candidate_hash") != candidate.get("candidate_hash"):
        raise MaterialError("主张审计使用了不同候选人版本")
    known = _facts(candidate)
    for claim in audit.get("claims", []):
        ids = claim.get("fact_ids", [])
        if len(ids) != 1 or ids[0] not in known:
            raise MaterialError("每项候选人主张必须映射到一个审核事实句子")
        fact_id = ids[0]
        approved_text(candidate, fact_id, claim.get("text"))
        if claim.get("source_hashes") != [known[fact_id]["source"]["sha256"]] or claim.get("fact_versions") != [known[fact_id]["version"]]:
            raise MaterialError("主张来源哈希或事实版本被篡改")


def build_packet(observation: dict, candidate: dict, assessment: dict,
                 output_dir: str | Path | None = None) -> dict:
    verify_candidate_current(candidate)
    text = jd_text(observation)
    verify_requirement_offsets(assessment, text)
    fresh = assess(observation, candidate)
    if canonical_hash(assessment) != canonical_hash(fresh):
        raise MaterialError("岗位评估已过期或被修改；请重新运行匹配")
    if assessment.get("candidate_hash") != candidate["candidate_hash"]:
        raise MaterialError("评估与候选人事实版本不一致")
    key = canonical_hash({"job_id": job_id(observation), "jd": assessment["jd_hash"],
                          "candidate": candidate["candidate_hash"], "version": MATERIAL_VERSION})[:24]
    output = Path(output_dir) if output_dir else PROJECT_ROOT / "private" / "packets" / key
    output = output.resolve()
    if not output.is_relative_to(PROJECT_ROOT / "private"):
        raise MaterialError("投递包含个人信息，只能写入本项目private目录")
    output.mkdir(parents=True, exist_ok=True)
    baseline_path = Path(candidate["baseline"]["resolved_path"])
    baseline_bytes = baseline_path.read_bytes()
    if sha256_bytes(baseline_bytes) != candidate["baseline_hash"]:
        raise MaterialError("原简历基线已变化")
    baseline = baseline_bytes.decode("utf-8-sig")
    resume, claims, blocks = _resume(candidate, observation, assessment)
    outreach, additional = _outreach(candidate, observation)
    claims += additional
    audit = {"schema_version": "career-claim-audit-v1", "material_version": MATERIAL_VERSION,
             "candidate_hash": candidate["candidate_hash"], "baseline_hash": candidate["baseline_hash"],
             "jd_hash": assessment["jd_hash"], "claims": claims,
             "identity_source": {"path": candidate["_profile_path"], "sha256": candidate["candidate_hash"],
                                 "fields": ["identity.name", "identity.contact"]},
             "target_label_source": {"field": "JD role_title/title", "jd_hash": assessment["jd_hash"],
                                     "boundary": "应聘岗位标签，不是候选人能力主张"},
             "review_state": "needs_review", "canonical_status": "candidate"}
    verify_claim_audit(candidate, audit)
    diff = "".join(difflib.unified_diff(baseline.splitlines(keepends=True), resume.splitlines(keepends=True),
                   fromfile="user-original-v4.2-onepage", tofile="tailored-approved-facts", n=3))
    # Store the exact baseline bytes used for the diff, not a generated substitute.
    (output / "baseline-original.md").write_bytes(baseline_bytes)
    files = {"jd": output / "jd-original.txt", "assessment": output / "assessment.json",
             "assessment_md": output / "assessment.md", "resume_md": output / "resume.md",
             "resume_html": output / "resume.html", "resume_pdf": output / "resume.pdf",
             "claim_audit": output / "claim-audit.json", "diff": output / "baseline-to-tailored.diff",
             "baseline": output / "baseline-original.md", "greeting": output / "greeting.txt",
             "email": output / "email-draft.txt", "intro": output / "intro-30-seconds.txt",
             "evidence": output / "related-evidence.json", "review": output / "review.md"}
    _write(files["jd"], text)
    _write(files["assessment"], _json(assessment))
    _write(files["assessment_md"], _assessment_md(observation, assessment))
    _write(files["resume_md"], resume)
    _write(files["resume_html"], resume_html(blocks))
    _write(files["claim_audit"], _json(audit))
    _write(files["diff"], diff)
    for kind, content in outreach.items():
        _write(files[kind], content)
    official = _url(observation.get("official_apply_url") or observation.get("official_url"))
    source_url = _url(observation.get("source_url") or observation.get("url"))
    review = (_provenance("career-ops packet awaiting controller and user review") + "# 投递包审阅\n\n"
              f"目标岗位：{_md(job_title(observation))}\n\n"
              f"匹配建议：`{assessment['decision']}`。当前仅为可审阅材料；尚未批准、发送或登记投递。\n\n"
              "核对岗位原文、逐项要求与证据、真实基线差异和主张审计后，再对本版本做人工批准。任何 JD、事实或材料变化均使旧批准失效。\n\n"
              "官方申请 URL：" + (_md(official) if official else "未核验，不提供猜测地址") + "\n\n"
              "公开岗位来源：" + (_md(source_url) if source_url else "未知") + "\n\n"
              "自我介绍为约30秒的口述草稿；请按实际语速核对。历史项目验收数字保留当时版本与日期，不表示今天重跑。\n")
    _write(files["review"], review)
    from .pdf import write_resume_pdf
    try:
        pdf_metadata = write_resume_pdf(blocks, files["resume_pdf"])
    except Exception as error:
        raise MaterialError(f"PDF生成失败，包未达到review_ready：{error}") from error
    file_hashes = {kind: sha256_bytes(path.read_bytes()) for kind, path in files.items()}
    manifest = {"schema_version": "career-packet-v1", "material_version": MATERIAL_VERSION,
                "packet_key": key, "job_id": job_id(observation), "status": "review_ready",
                "candidate_hash": candidate["candidate_hash"], "baseline_hash": candidate["baseline_hash"],
                "jd_hash": assessment["jd_hash"], "assessment_hash": canonical_hash(assessment),
                "official_apply_url": official, "source_url": source_url,
                "files": {kind: str(path) for kind, path in files.items()}, "file_hashes": file_hashes,
                "pdf": pdf_metadata, "created_at": datetime.now(timezone.utc).isoformat(),
                "producer": "codex", "producer_role": "foreground-worker", "review_owner": "codex-controller",
                "review_state": "needs_review", "canonical_status": "candidate",
                "approval_boundary": "人工批准必须绑定本manifest和文件哈希；review_ready不是applied"}
    manifest["manifest_hash"] = canonical_hash(manifest)
    _write(output / "manifest.json", _json(manifest))
    packet = {**manifest, "manifest": manifest, "manifest_path": str(output / "manifest.json"), "output_dir": str(output)}
    verify_packet(packet, candidate)
    return packet


def verify_packet(packet: dict | str | Path, candidate: dict | None = None) -> dict:
    if isinstance(packet, (str, Path)):
        path = Path(packet)
        if path.is_dir():
            path = path / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
    else:
        manifest = packet.get("manifest", packet)
    recorded = manifest.get("manifest_hash")
    clean = {k: v for k, v in manifest.items() if k != "manifest_hash"}
    if recorded != canonical_hash(clean):
        raise MaterialError("manifest被修改")
    for kind, raw_path in manifest["files"].items():
        path = Path(raw_path).resolve()
        if not path.is_relative_to(PROJECT_ROOT / "private"):
            raise MaterialError("manifest文件路径超出private目录")
        if not path.is_file() or sha256_bytes(path.read_bytes()) != manifest["file_hashes"].get(kind):
            raise MaterialError(f"投递材料已被修改或丢失：{kind}")
    files = manifest["files"]
    jd = Path(files["jd"]).read_bytes().decode("utf-8")
    if sha256_bytes(jd.encode("utf-8")) != manifest["jd_hash"]:
        raise MaterialError("JD原文哈希不符")
    baseline_bytes = Path(files["baseline"]).read_bytes()
    if sha256_bytes(baseline_bytes) != manifest["baseline_hash"]:
        raise MaterialError("原始基线哈希不符")
    resume = Path(files["resume_md"]).read_text(encoding="utf-8")
    expected_diff = "".join(difflib.unified_diff(baseline_bytes.decode("utf-8-sig").splitlines(keepends=True),
                    resume.splitlines(keepends=True), fromfile="user-original-v4.2-onepage", tofile="tailored-approved-facts", n=3))
    if expected_diff != Path(files["diff"]).read_bytes().decode("utf-8"):
        raise MaterialError("diff不是由真实原始基线与当前岗位简历生成")
    if candidate:
        verify_candidate_current(candidate)
        if manifest["candidate_hash"] != candidate["candidate_hash"]:
            raise MaterialError("投递包候选人版本已经失效")
        verify_claim_audit(candidate, json.loads(Path(files["claim_audit"]).read_text(encoding="utf-8")))
        if manifest["baseline_hash"] != candidate["baseline_hash"]:
            raise MaterialError("投递包baseline版本已经失效")
    return manifest
