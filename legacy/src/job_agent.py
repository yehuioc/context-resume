"""Read-only compatibility; career owns all state and mutation."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]

def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    reads = {"status": "status", "doctor": "status", "init": "status", "verify": "status",
             "list": "list", "show": "show", "report": "funnel"}
    if command not in reads:
        print(json.dumps({"ok": False, "error": "旧写入入口已停用，请使用统一 career 入口。"}, ensure_ascii=False))
        return 1
    sys.path.insert(0, str(ROOT))
    from career_ops.cli import main as career_main
    return career_main([reads[command], *sys.argv[2:]])

if __name__ == "__main__":
    raise SystemExit(main())
