import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import render_pack

def test_unchecked_preview_cannot_bypass_evidence_review(tmp_path):
    with pytest.raises(SystemExit) as failure:
        render_pack.main(["--input", str(tmp_path / "input.json"), "--out", str(tmp_path / "out")])
    assert failure.value.code == 2
    assert not (tmp_path / "out").exists()
