import copy
import json
from pathlib import Path

import pytest

from career_ops.candidate import CandidateError, canonical_hash, sha256_bytes
from career_ops.materials import MaterialError, build_packet, verify_packet, resume_html
from career_ops.matching import assess
from career_ops.pdf import inspect_pdf
from test_matching import make_candidate, job


@pytest.fixture
def packet_context(tmp_path):
    candidate = make_candidate(tmp_path)
    observation = job("任职要求\n了解MCP与Agent工作流，Coze经验优先。")
    assessment = assess(observation, candidate)
    return candidate, observation, assessment, tmp_path / "packet"


def test_complete_packet_true_baseline_diff_and_pdf(packet_context):
    candidate, observation, assessment, output = packet_context
    packet = build_packet(observation, candidate, assessment, output)
    assert packet["status"] == "review_ready"
    assert packet["candidate_hash"] == candidate["candidate_hash"]
    assert packet["baseline_hash"] == candidate["baseline_hash"]
    assert Path(packet["files"]["baseline"]).read_bytes() == Path(candidate["baseline"]["resolved_path"]).read_bytes()
    diff = Path(packet["files"]["diff"]).read_text(encoding="utf-8")
    assert "- RAG / 文档检索" in diff
    assert "不包含完整向量召回与重排序" in diff
    resume = Path(packet["files"]["resume_md"]).read_text(encoding="utf-8")
    assert "本人负责需求" in resume and "预计2028年毕业" in resume
    audit = json.loads(Path(packet["files"]["claim_audit"]).read_text(encoding="utf-8"))
    assert all(claim["fact_ids"] and claim["source_hashes"] and claim["fact_versions"] for claim in audit["claims"])
    pdf = inspect_pdf(packet["files"]["resume_pdf"])
    assert pdf["page_count"] == 1
    assert "测试候选人" in pdf["text"] and "本人负责需求" in pdf["text"]
    assert len(json.loads(Path(packet["files"]["evidence"]).read_text(encoding="utf-8"))) == 3
    assert verify_packet(packet, candidate)["status"] == "review_ready"


def test_candidate_fact_injection_cannot_keep_old_hash(packet_context):
    candidate, observation, assessment, output = packet_context
    injected = copy.deepcopy(candidate)
    injected["facts"][4]["text"] = "精通Python与独立开发"
    with pytest.raises(CandidateError, match="修改"):
        build_packet(observation, injected, assessment, output)


def test_derived_fact_index_cannot_inject_claim_text(packet_context):
    candidate, observation, assessment, output = packet_context
    injected = copy.deepcopy(candidate)
    injected["_facts_by_id"]["PY"] = {**injected["_facts_by_id"]["PY"], "text": "精通Python且独立开发生产系统"}
    packet = build_packet(observation, injected, assessment, output)
    resume = Path(packet["files"]["resume_md"]).read_text(encoding="utf-8")
    assert "精通Python且独立开发生产系统" not in resume
    assert "Python项目实践以AI协作为主" in resume


def test_unapproved_fact_variant_and_assessment_changes_rejected(packet_context):
    candidate, observation, assessment, output = packet_context
    changed = copy.deepcopy(assessment)
    changed["decision"] = "applied"
    with pytest.raises(MaterialError, match="过期|修改"):
        build_packet(observation, candidate, changed, output)


def test_diff_tampering_caught_even_after_file_hash_recomputed(packet_context):
    candidate, observation, assessment, output = packet_context
    packet = build_packet(observation, candidate, assessment, output)
    manifest = copy.deepcopy(packet["manifest"])
    diff = Path(manifest["files"]["diff"])
    diff.write_text("fake original baseline", encoding="utf-8")
    manifest["file_hashes"]["diff"] = sha256_bytes(diff.read_bytes())
    manifest.pop("manifest_hash")
    manifest["manifest_hash"] = canonical_hash(manifest)
    with pytest.raises(MaterialError, match="真实原始基线"):
        verify_packet(manifest, candidate)


def test_html_and_jd_title_injection_is_inert(packet_context):
    candidate, observation, _, output = packet_context
    observation["role_title"] = '<script>alert("x")</script>AI Agent'
    packet = build_packet(observation, candidate, assess(observation, candidate), output)
    rendered = Path(packet["files"]["resume_html"]).read_text(encoding="utf-8")
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "Content-Security-Policy" in rendered
    assert "<img" not in resume_html([{"kind": "bullet", "text": '<img src=x onerror="alert(1)">'}])


def test_baseline_mutation_after_loading_is_blocked(packet_context):
    candidate, observation, assessment, output = packet_context
    Path(candidate["baseline"]["resolved_path"]).write_text("made up", encoding="utf-8")
    with pytest.raises(CandidateError, match="原始简历"):
        build_packet(observation, candidate, assessment, output)


def test_packet_cannot_write_personal_data_outside_private(packet_context):
    candidate, observation, assessment, _ = packet_context
    with pytest.raises(MaterialError, match="private"):
        build_packet(observation, candidate, assessment, Path(__file__).parent / "not-private")
