"""Persisted material references survive moving the module; traversal fails."""
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from career_ops import config
from career_ops.config import private_path
from career_ops.materials import build_packet, verify_packet
from career_ops.matching import assess
from career_ops.workflow import Workflow
from career_ops.review import file_preview
from test_matching import make_candidate, job


def test_packet_and_preview_survive_relocation_with_original_unavailable(tmp_path):
    candidate = make_candidate(tmp_path)
    observation = job("任职要求\n了解MCP与Agent工作流，Coze经验优先。")
    original = tmp_path / "packet"
    packet = build_packet(observation, candidate, assess(observation, candidate), original)
    artifacts = Workflow.collect_artifacts(packet, original)
    assert all(not Path(value).is_absolute() for value in packet["files"].values())
    relative = original.relative_to(config.PROJECT_ROOT)
    module = tmp_path / "relocated-career"
    relocated = module / relative
    shutil.copytree(original, relocated)
    original.rename(tmp_path / "original-disabled")
    with patch.object(config, "PROJECT_ROOT", module):
        verify_packet(packet["manifest_path"])
        Workflow.verify_artifacts({"artifacts": artifacts})
        preview = file_preview(artifacts["resume_pdf"], "resume_pdf", relocated)
        assert 'href="resume.pdf"' in preview
        assert "file:///" not in preview
        for invalid in ("../outside.txt", "private/../../outside.txt", module.parent / "outside.txt"):
            with pytest.raises(ValueError): private_path(invalid)
