"""Command line review and recordkeeping; intentionally no send command."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from .store import DEFAULT_DB, PROJECT_ROOT, StateError, Store
from .workflow import Workflow
from .candidate import DEFAULT_PROFILE
from .config import private_path


def write_json(value: object, output: str | Path | None = None) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if output:
        path = Path(output).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def validate_collection_evidence(observations: list[dict], evidence_dir: str | Path) -> None:
    directory = private_path(evidence_dir)
    if not directory.is_relative_to((PROJECT_ROOT / "private").resolve()):
        raise StateError("采集证据必须位于本项目private目录")
    checked: set[tuple[str, str]] = set()
    def visit(value: object) -> int:
        count = 0
        if isinstance(value, dict):
            if "raw_path" in value:
                raw_path = private_path(value["raw_path"])
                expected = str(value.get("sha256", ""))
                if not raw_path.is_relative_to(directory) or not raw_path.is_file() or not expected:
                    raise StateError("采集原始响应文件缺失或越界")
                key = (str(raw_path), expected)
                if key not in checked:
                    if hashlib.sha256(raw_path.read_bytes()).hexdigest() != expected:
                        raise StateError("采集原始响应摘要不一致")
                    metadata_path = private_path(value.get("metadata_path", ""))
                    if not metadata_path.is_relative_to(directory) or not metadata_path.is_file():
                        raise StateError("采集响应元数据缺失或越界")
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
                    if metadata.get("sha256") != expected or metadata.get("requested_url") != value.get("requested_url"):
                        raise StateError("原始响应与元数据不一致")
                    checked.add(key)
                count += 1
            for nested in value.values():
                if isinstance(nested, (dict, list)):
                    count += visit(nested)
        elif isinstance(value, list):
            count += sum(visit(nested) for nested in value)
        return count
    for observation in observations:
        if not visit(observation.get("verification_evidence")):
            raise StateError("采集Observation没有可核对的原始响应，不能继承核验状态")
        from .sources import validate_collected_observation
        validate_collected_observation(observation)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="本地求职执行系统：审阅、人工批准、确认投递与反馈；不自动发送")
    p.add_argument("--db", default=os.environ.get("CAREER_OPS_DB", str(DEFAULT_DB)))
    p.add_argument("--candidate", help=f"显式指定已审核事实文件；当前默认：{DEFAULT_PROFILE}")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "funnel", "next-actions"):
        sub.add_parser(name)
    listing = sub.add_parser("list"); listing.add_argument("--status"); listing.add_argument("--limit", type=int, default=100)
    show = sub.add_parser("show"); show.add_argument("opportunity_id", type=int)
    imp = sub.add_parser("import"); imp.add_argument("--file", required=True); imp.add_argument("--receipt", help="采集回执；按selected_file和selected_sha256核对本地采集结果，保留原核验状态")
    discovery = sub.add_parser("discover"); discovery.add_argument("provider", choices=("ncss", "greenhouse")); discovery.add_argument("--keyword", default=""); discovery.add_argument("--board", default="anthropic"); discovery.add_argument("--limit", type=int, default=20); discovery.add_argument("--max-pages", type=int, default=3); discovery.add_argument("--timeout", type=float, default=15)
    verify = sub.add_parser("verify"); verify.add_argument("opportunity_id", type=int); verify.add_argument("--timeout", type=float, default=15)
    for name in ("assess", "prepare"):
        action = sub.add_parser(name); action.add_argument("opportunity_id", type=int, nargs="?"); action.add_argument("--all", action="store_true"); action.add_argument("--limit", type=int, default=100)
    decision = sub.add_parser("human-decision"); decision.add_argument("opportunity_id", type=int); decision.add_argument("decision", choices=("shortlist", "hold", "reject")); decision.add_argument("--actor", required=True); decision.add_argument("--note", default="")
    shortlist = sub.add_parser("shortlist"); shortlist.add_argument("opportunity_id", type=int); shortlist.add_argument("--actor", required=True); shortlist.add_argument("--note", default="")
    approve = sub.add_parser("approve"); approve.add_argument("packet_id", type=int); approve.add_argument("--digest", required=True); approve.add_argument("--actor", required=True); approve.add_argument("--note", default=""); approve.add_argument("--confirm-reviewed", action="store_true", required=True); approve.add_argument("--accept-unknowns", action="store_true"); approve.add_argument("--review-note", default="")
    applied = sub.add_parser("mark-applied"); applied.add_argument("packet_id", type=int); applied.add_argument("--confirmation", required=True, choices=("user_confirmation", "platform_receipt")); applied.add_argument("--evidence", required=True); applied.add_argument("--sent-at"); applied.add_argument("--confirm-sent", action="store_true", required=True)
    reply = sub.add_parser("record-reply"); reply.add_argument("opportunity_id", type=int); reply.add_argument("--type", required=True, choices=("hr_reply", "hiring_manager_reply", "interview", "rejected", "offer", "withdrawn", "no_response", "note")); reply.add_argument("--content", required=True); reply.add_argument("--occurred-at"); reply.add_argument("--event-id"); reply.add_argument("--contact-name"); reply.add_argument("--contact-role", choices=("hr", "hiring_manager", "other"), default="other"); reply.add_argument("--contact-channel", default=""); reply.add_argument("--contact-address", default=""); reply.add_argument("--next-action"); reply.add_argument("--due-at")
    review = sub.add_parser("review"); review.add_argument("opportunity_id", type=int); review.add_argument("--packet", type=int); review.add_argument("--output")
    report = sub.add_parser("report"); report.add_argument("--output", default=str(PROJECT_ROOT / "private" / "review" / "index.html")); report.add_argument("--limit", type=int, default=100)
    export = sub.add_parser("export"); export.add_argument("--output", default=str(PROJECT_ROOT / "private" / "exports" / "career-ops-readonly.json"))
    migration = sub.add_parser("migrate-legacy"); migration.add_argument("--source", default=str(PROJECT_ROOT.parent / "legacy" / "var" / "job-agent.sqlite3"))
    return p


def run(args: argparse.Namespace) -> object:
    with Store(args.db) as store:
        workflow = Workflow(store, args.candidate)
        command = args.command
        if command in {"init", "status"}:
            return {"ok": True, "version": "0.1.0", "authority": str(store.path), "candidate_authority": str(Path(args.candidate).resolve() if args.candidate else DEFAULT_PROFILE), "send_enabled": False, "funnel": store.funnel()}
        if command == "list":
            return {"ok": True, "opportunities": store.list_opportunities(status=args.status, limit=args.limit)}
        if command == "show":
            return store.get_opportunity(args.opportunity_id)
        if command == "import":
            from .sources import import_manual
            import_path = Path(args.file).resolve()
            data = json.loads(import_path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                observations = data.get("observations", data.get("samples", [data]))
            else:
                observations = data
            if not isinstance(observations, list):
                raise StateError("导入文件必须是Observation列表或observations/samples对象")
            if args.receipt:
                receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8-sig"))
                if private_path(receipt.get("selected_file", "")) != import_path or receipt.get("selected_sha256") != hashlib.sha256(import_path.read_bytes()).hexdigest():
                    raise StateError("采集文件与回执不一致；不能继承核验状态")
                if "scripts/collect_samples.py" not in receipt.get("commands", "") or not receipt.get("evidence_dir"):
                    raise StateError("不是本项目可追溯的采集回执")
                for obs in observations:
                    channel = str(obs.get("source_channel", ""))
                    if not (channel == "ncss" or channel.startswith("greenhouse:")) or not obs.get("verification_evidence"):
                        raise StateError("采集观察缺少支持的来源及独立核验证据")
                validate_collection_evidence(observations, receipt["evidence_dir"])
                imported = observations
            else:
                imported = [import_manual(obs) for obs in observations]
            return {"ok": True, "results": [store.ingest_observation(obs) for obs in imported], "note": "采集回执保持来源证据，不代表岗位适配、人工批准或发送。" if args.receipt else "手工输入继承为未核验；不能自称verified。"}
        if command == "discover":
            from .sources import collect_greenhouse, collect_ncss
            evidence_dir = PROJECT_ROOT / "private" / "sources"
            kwargs = {"limit": args.limit, "max_pages": args.max_pages, "timeout": args.timeout, "evidence_dir": evidence_dir}
            observations = collect_ncss(args.keyword, **kwargs) if args.provider == "ncss" else collect_greenhouse(args.board, **kwargs)
            return {"ok": True, "provider": args.provider, "results": [store.ingest_observation(obs) for obs in observations]}
        if command == "verify":
            from .sources import verify_observation
            obs = store.get_opportunity(args.opportunity_id)["observation"]
            verified = verify_observation(obs, timeout=args.timeout, evidence_dir=PROJECT_ROOT / "private" / "sources")
            return {"ok": True, "verification": verified, "result": store.ingest_observation(verified)}
        if command in {"assess", "prepare"}:
            if args.all:
                ids = [r["id"] for r in store.list_opportunities(limit=args.limit)]
            elif args.opportunity_id:
                ids = [args.opportunity_id]
            else:
                raise StateError("请指定机会id或--all")
            results = []
            for opportunity_id in ids:
                try:
                    result = workflow.assess(opportunity_id) if command == "assess" else workflow.prepare(opportunity_id)
                    results.append({"ok": True, **result})
                except (ValueError, RuntimeError, OSError) as exc:
                    if not args.all:
                        raise
                    results.append({"ok": False, "opportunity_id": opportunity_id, "error": str(exc)})
            return {"ok": all(r["ok"] for r in results), "results": results}
        if command in {"human-decision", "shortlist"}:
            decision = "shortlist" if command == "shortlist" else args.decision
            return {"ok": True, "human_decision_id": workflow.human_decision(args.opportunity_id, decision, actor=args.actor, note=args.note), "note": "人工shortlist仍不代表批准材料或实际发送。"}
        if command == "approve":
            return {"ok": True, "approval_id": workflow.approve(args.packet_id, actor=args.actor, expected_digest=args.digest, note=args.note, accept_unknowns=args.accept_unknowns, review_note=args.review_note), "note": "批准已绑定本次材料摘要与人工风险说明；Unknown原样保留，尚未登记发送。"}
        if command == "mark-applied":
            return {"ok": True, "application_id": workflow.mark_applied(args.packet_id, confirmation_type=args.confirmation, evidence=args.evidence, sent_at=args.sent_at)}
        if command == "record-reply":
            contact = {"name": args.contact_name, "role": args.contact_role, "channel": args.contact_channel, "address": args.contact_address} if args.contact_name else None
            return {"ok": True, "interaction_id": store.record_interaction(args.opportunity_id, args.type, args.content, occurred_at=args.occurred_at, event_id=args.event_id, contact=contact, next_action=args.next_action, due_at=args.due_at)}
        if command == "funnel":
            return store.funnel()
        if command == "next-actions":
            return {"ok": True, "next_actions": store.export_readonly()["next_actions"]}
        if command == "review":
            from .review import render_review
            opportunity = store.get_opportunity(args.opportunity_id)
            packet = store.get_packet(args.packet) if args.packet else next((p for p in opportunity["packets"] if p["revision_id"] == opportunity["current_revision_id"]), None)
            if packet and packet["opportunity_id"] != args.opportunity_id:
                raise StateError("材料包不属于本机会")
            path = render_review(opportunity, packet, args.output or PROJECT_ROOT / "private" / "review" / f"opportunity-{args.opportunity_id}.html")
            return {"ok": True, "review_path": str(path)}
        if command == "report":
            from .review import render_report
            return {"ok": True, "report_path": str(render_report(store, args.output, limit=args.limit)), "funnel": store.funnel()}
        if command == "export":
            write_json(store.export_readonly(), args.output)
            return {"ok": True, "export_path": str(Path(args.output).resolve()), "writable": False}
        if command == "migrate-legacy":
            return {"ok": True, **store.migrate_legacy(args.source)}
        raise StateError(f"未知命令：{command}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        result = run(args)
        write_json(result)
        return 1 if isinstance(result, dict) and result.get("ok") is False else 0
    except Exception as exc:
        write_json({"ok": False, "error": str(exc)})
        return 1
