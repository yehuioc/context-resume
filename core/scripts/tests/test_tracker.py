import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tracker

@pytest.mark.parametrize("command", ["add", "update", "send"])
def test_old_tracker_cannot_create_sent_state(command):
    with pytest.raises(SystemExit, match="写入已停用"):
        tracker.main([command])
