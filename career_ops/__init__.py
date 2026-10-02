"""Unified-root entry; all business implementation lives in career/career_ops."""
from pathlib import Path

__path__ = [str(Path(__file__).resolve().parents[1] / "career" / "career_ops")]
