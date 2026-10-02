"""Escaped, offline Chinese views. Views never approve or send applications."""
from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import urlsplit

from .store import Store


STYLE = """body{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:auto;max-width:1180px;padding:32px;color:#18232f;background:#f4f6f8}h1{font-size:28px}h2{font-size:21px;border-bottom:1px solid #cdd7df;padding-bottom:8px}section{background:white;padding:24px;margin:18px 0;border-radius:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit;line-height:1.7}table{width:100%;border-collapse:collapse}td,th{padding:10px;text-align:left;border-bottom:1px solid #ddd}a{color:#075cac}code{overflow-wrap:anywhere}.warning{border-left:5px solid #d9a000;padding:16px;background:#fff3cb}.meta{color:#546574}.tag{display:inline-block;padding:4px 8px;background:#e5eef6;border-radius:4px}summary{cursor:pointer;font-weight:600}details{margin-top:10px}nav a{margin-right:20px}"""


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def json_block(value: object) -> str:
    return "<pre>" + esc(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"


def safe_link(url: str, label: str) -> str:
    if urlsplit(url).scheme.lower() not in {"http", "https"}:
        return esc(url or "未提供")
    return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(label)}</a>'


def file_preview(artifact: dict, label: str) -> str:
    path = Path(artifact["path"])
    link = f'<a href="{esc(path.as_uri())}">{esc(label)}：{esc(path.name)}</a>'
    if path.suffix.lower() in {".md", ".txt", ".json", ".html"} and path.is_file():
        # HTML is shown as escaped source; external JD or draft content cannot execute.
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        return link + f"<details open><summary>完整内容</summary><pre>{esc(content)}</pre></details>"
    return link + f'<p class="meta">SHA256：{esc(artifact["sha256"])}</p>'


def document(title: str, body: str) -> str:
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:; base-uri \'none\'; form-action \'none\'"><title>{esc(title)}</title><style>{STYLE}</style></head><body>{body}</body></html>'


def render_review(opportunity: dict, packet: dict | None, output_path: str | Path) -> Path:
    obs = opportunity["observation"]
    title = f'{opportunity["company"]} · {opportunity["role_title"]}'
    parts = [f'<h1>{esc(title)}</h1><p class="meta">机会 #{opportunity["id"]} · {esc(opportunity["location"])} · 当前状态 {esc(opportunity["status"])} · 来源核验 {esc(obs.get("verification_status", "unknown"))}</p>', '<p class="warning">这是本地只读审阅页。系统建议不代表人工 shortlist；人工批准不代表已发送。官方平台的最后点击由用户完成，再单独登记发送证据。</p>']
    employer_verified = obs.get("verification_status") == "employer_verified"
    primary_url = str(obs.get("official_url") or "") if employer_verified else str(obs.get("source_url") or "")
    primary_label = "已核验雇主官方申请入口" if employer_verified else ("官方平台岗位入口" if obs.get("verification_status") == "official_platform_live" else "未核验来源入口")
    parts.append('<section><h2>岗位来源与风险</h2>' + safe_link(primary_url, primary_label) + "<p>原来源：" + safe_link(str(obs.get("source_url") or ""), "查看来源页面") + "</p>" + json_block({"verification_evidence": obs.get("verification_evidence"), "risk_flags": obs.get("risk_flags"), "aliases": opportunity["aliases"]}) + "</section>")
    parts.append('<section><h2>完整原始 JD</h2><pre>' + esc(obs.get("jd_raw", "")) + '</pre><p class="meta">JD SHA256：' + esc(opportunity["revision"]["jd_hash"]) + "</p></section>")
    assessment = packet["payload"].get("assessment") if packet else None
    if not assessment and packet:
        assessment = next((s["payload"] for s in opportunity["assessments"] if s["id"] == packet["assessment_id"]), None)
    if not assessment and opportunity["assessments"]:
        assessment = opportunity["assessments"][0]["payload"]
    if assessment:
        parts.append('<section><h2>本岗位审阅摘要</h2>' + assessment_summary(assessment) + "</section>")
        requirement_rows = []
        for requirement in assessment.get("requirements", []):
            evidence = requirement.get("evidence", requirement.get("components", []))
            requirement_rows.append("<tr>" + "".join(f"<td>{esc(value)}</td>" for value in (requirement.get("id", ""), requirement.get("quote", ""), requirement.get("priority", ""), requirement.get("status", ""), json.dumps(evidence, ensure_ascii=False))) + "</tr>")
        table = '<table><tr><th>要求ID</th><th>JD原句</th><th>必选/加分</th><th>证据状态</th><th>证据或待确认</th></tr>' + "".join(requirement_rows) + "</table>"
        parts.append('<section><h2>需求、证据与未知：R / E / U / V</h2>' + table + '<details><summary>完整逐项评估、来源与偏移证据</summary>' + json_block(assessment) + "</details></section>")
    if packet:
        parts.append('<section><h2>本次材料版本</h2>' + json_block({key: packet[key] for key in ("id", "packet_digest", "candidate_hash", "jd_hash", "revision_id", "assessment_id")}) + "</section>")
        for label, artifact in packet["artifacts"].items():
            parts.append(f'<section><h2>{esc(label)}</h2>{file_preview(artifact, label)}</section>')
    parts.append('<section><h2>人工决定、真实投递与回复</h2>' + json_block({key: opportunity[key] for key in ("human_decisions", "approvals", "application", "interactions", "contacts", "next_actions")}) + "</section>")
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document(title, "".join(parts)), encoding="utf-8")
    return path


def reasons(entries: list | None, *, limit: int = 3) -> str:
    return "；".join(str(e.get("reason", e.get("quote", e))) if isinstance(e, dict) else str(e) for e in (entries or [])[:limit]) or "无"


def assessment_summary(assessment: dict) -> str:
    direct = [r.get("quote", "") for r in assessment.get("requirements", []) if r.get("status") == "direct"]
    return f'<p>系统建议：<strong>{esc(assessment.get("decision", "hold"))}</strong>。排序分 {esc(assessment.get("rank_score", "—"))} 仅辅助审阅。</p><p>关键匹配：{esc("；".join(direct[:3]) or "未找到直接证据覆盖")}</p><p>必填未知：{esc(reasons(assessment.get("unknown_required")))}</p><p>硬条件冲突：{esc(reasons(assessment.get("hard_conflicts")))}</p>'


def render_report(store: Store, output_path: str | Path, *, limit: int = 100) -> Path:
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    legacy_rows = []
    candidates = []
    for row in store.list_opportunities(limit=limit):
        opportunity = store.get_opportunity(row["id"])
        assessment = next((s["payload"] for s in opportunity["assessments"] if s["revision_id"] == opportunity["current_revision_id"]), {})
        candidates.append((row, opportunity, assessment))
    candidates.sort(key=lambda item: (bool(item[1]["observation"].get("jd_raw", "").strip()), item[2].get("decision") == "suggested_shortlist", item[2].get("decision") != "reject", float(item[2].get("rank_score", 0))), reverse=True)
    priority = []
    for row, opportunity, assessment in candidates:
        packet = next((p for p in opportunity["packets"] if p["revision_id"] == opportunity["current_revision_id"]), None)
        detail_path = path.parent / f'opportunity-{row["id"]}.html'
        render_review(opportunity, packet, detail_path)
        direct = "；".join(r.get("quote", "") for r in assessment.get("requirements", []) if r.get("status") == "direct")
        table_row = f'<tr><td><a href="{esc(detail_path.name)}">#{row["id"]} {esc(row["company"])}</a></td><td>{esc(row["role_title"])}</td><td>{esc(row["location"])}</td><td>{esc(row["verification_status"])}</td><td>{esc(row.get("suggested_decision"))}<br>排序分 {esc(assessment.get("rank_score", "—"))}</td><td>{esc(direct[:300] or "暂无直接覆盖")}<br><strong>待核验：</strong>{esc(reasons(assessment.get("unknown_required")))}<br><strong>硬冲突：</strong>{esc(reasons(assessment.get("hard_conflicts")))}</td><td>{esc(row["status"])}</td></tr>'
        if opportunity["observation"].get("jd_raw", "").strip():
            rows.append(table_row)
            if len(priority) < 5 and assessment.get("decision") != "reject":
                priority.append(f'<li><a href="{esc(detail_path.name)}">#{row["id"]} {esc(row["company"])} · {esc(row["role_title"])}</a> — {esc(reasons(assessment.get("unknown_required"), limit=2))}</li>')
        else:
            legacy_rows.append(table_row)
    header = '<table><thead><tr><th>公司 / 详情</th><th>岗位</th><th>地点</th><th>核验</th><th>系统建议</th><th>匹配与待核验</th><th>真实状态</th></tr></thead><tbody>'
    body = '<h1>求职机会与投递审阅</h1><p class="warning">建议 shortlist 与人工决定分列。此导出只读；所有批准和真实发送确认通过本地命令明确记录。排序分只帮助安排阅读顺序，不能覆盖未知条件和硬冲突。</p><section><h2>优先审阅与补证据</h2><ol>' + "".join(priority) + '</ol></section><section><h2>已有完整 JD 的机会</h2>' + header + "".join(rows) + '</tbody></table></section><section><details><summary>历史线索与缺少 JD 的机会</summary>' + header + "".join(legacy_rows) + '</tbody></table></details></section><section><h2>历史事件漏斗</h2>' + json_block(store.funnel()) + "</section>"
    path.write_text(document("求职机会与投递审阅", body), encoding="utf-8")
    return path
