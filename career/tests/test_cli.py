import json
import os
from pathlib import Path
import subprocess
import sys

from career_ops.candidate import DEFAULT_PROFILE, PROJECT_ROOT, load_candidate
from career_ops import config


def run_status(tmp_path, *arguments, environment=None):
    result = subprocess.run(
        [sys.executable, "-B", "-m", "career_ops", "--db", str(tmp_path / "state.sqlite3"), *arguments, "status"],
        cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(result.stdout)


def test_status_reports_actual_default_and_explicit_fact_sources(tmp_path):
    assert Path(run_status(tmp_path)["candidate_authority"]) == DEFAULT_PROFILE
    example = PROJECT_ROOT / "examples/career-profile.json"
    assert Path(run_status(tmp_path, "--candidate", str(example))["candidate_authority"]) == example


def test_standalone_example_overrides_machine_config_without_real_data(tmp_path):
    example = PROJECT_ROOT / "examples/career-profile.json"
    environment = dict(os.environ, CAREER_WORKSPACE_ROOT=str(PROJECT_ROOT), CAREER_OPS_CANDIDATE=str(example))
    assert Path(run_status(tmp_path, environment=environment)["candidate_authority"]) == example
    assert load_candidate(example)["example_only"] is True


def test_private_configuration_resolves_paths_and_environment_wins(tmp_path, monkeypatch):
    settings = tmp_path / "local-config.json"
    settings.write_text(json.dumps({"candidate_profile": "facts/profile.json"}), encoding="utf-8")
    monkeypatch.setattr(config, "LOCAL_CONFIG", settings)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("CAREER_OPS_CANDIDATE", raising=False)
    assert config.configured_path("candidate_profile", "unused", "CAREER_OPS_CANDIDATE") == tmp_path / "facts/profile.json"
    monkeypatch.setenv("CAREER_OPS_CANDIDATE", str(tmp_path / "other.json"))
    assert config.configured_path("candidate_profile", "unused", "CAREER_OPS_CANDIDATE") == tmp_path / "other.json"
