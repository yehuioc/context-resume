"""Read compatibility only; never create core/data/tracker.json."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    reads = {"list": "list", "stats": "funnel", "followup-due": "next-actions"}
    if not args or args[0] not in reads:
        raise SystemExit("旧 tracker 写入已停用；请使用 python -m career_ops，批准与发送需分别记录。")
    sys.path.insert(0, str(ROOT))
    from career_ops.cli import main as career_main
    return career_main([reads[args[0]], *args[1:]])

if __name__ == "__main__":
    raise SystemExit(main())
