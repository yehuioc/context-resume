"""Compatibility entry to the single source-validated evidence engine."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]

def main(argv=None):
    parser = argparse.ArgumentParser(description="证据包生成，必须独立提供来源清单与复核确认")
    parser.add_argument("--input", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--human-review-confirmed", required=True, action="store_true")
    args = parser.parse_args(argv)
    shell = shutil.which("pwsh")
    if not shell:
        parser.error("需要 PowerShell 7 (pwsh)")
    return subprocess.call([shell, "-NoProfile", "-File", str(ROOT / "engine/scripts/build-customer-pack.ps1"),
                            "-InputJson", args.input, "-SourceManifestJson", args.source_manifest,
                            "-OutputDir", args.out, "-HumanReviewConfirmed"])

if __name__ == "__main__":
    raise SystemExit(main())
