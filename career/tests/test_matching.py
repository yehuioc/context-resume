import json
from pathlib import Path

import pytest

from career_ops.candidate import CandidateError, load_candidate, sha256_bytes, approved_text
from career_ops.matching import assess, verify_requirement_offsets


def make_candidate(tmp_path):
    source = tmp_path / "reviewed-evidence.md"
    source.write_text("已审核测试证据：在读本科、AI协作、MCP只读桥接、关键词检索、4-5天。", encoding="utf-8")
    baseline = tmp_path / "original-v4.2.md"
    baseline.write_text("# 测试候选人\n\n## 技能\n\n- RAG / 文档检索\n\n本人以AI协作开发。\n", encoding="utf-8")
    fact_values = [
        ("ID", "identity", "测试候选人｜AI应用实习生"),
        ("ED", "education", "本科在读，电子信息工程，预计2028年毕业。"),
        ("ROLE", "role", "使用AI工具协作开发；本人负责需求、调试、验证与验收。"),
        ("PB", "project", "设计只读MCP桥接，支持本地原文读取与边界验收。"),
        ("PY", "skill", "Python项目实践以AI协作为主，独立编码熟练度待验证。"),
        ("SK", "skill", "文档检索采用关键词与路径查询，不包含完整向量召回与重排序。"),
        ("AV", "availability", "每周4-5天，本学期可参与，起始日期待确认。"),
    ]
    facts = [{"id": id_, "kind": kind, "text": text, "approved_variants": [],
              "version": "test-reviewed-v1", "review_state": "reviewed", "tags": [],
              "source": {"path": str(source), "sha256": sha256_bytes(source.read_bytes()), "locator": id_},
              **({"project_id": "project-brain", "project_name": "MCP只读桥接"} if kind == "project" else {})}
             for id_, kind, text in fact_values]
    profile = {"schema_version": "career-profile-v1", "profile_id": "test", "version": "test-v1", "review_state": "reviewed",
               "identity": {"name": "测试候选人", "education": {"level": "bachelor", "major": "电子信息工程", "graduation_year": 2028, "status": "enrolled"},
                            "contact": {"email": "test@example.invalid", "location": "广东"}},
               "availability": {"days_per_week_min": 4, "days_per_week_max": 5, "start_date": None, "duration_months": None,
                                "semester_available": True, "remote_preferred": True, "remote_only": False},
               "constraints": {"independent_python": None, "experience_years": None},
               "baseline": {"path": str(baseline), "sha256": sha256_bytes(baseline.read_bytes()), "version": "v4.2"},
               "facts": facts,
               "capabilities": [{"id": "mcp", "aliases": ["MCP"], "status": "direct", "fact_ids": ["PB"], "note": "真实AI协作只读桥接"},
                                {"id": "python", "aliases": ["Python"], "status": "partial", "fact_ids": ["PY", "ROLE"], "note": "AI协作实践，独立熟练度未知"},
                                {"id": "workflow", "aliases": ["Agent", "工作流", "自动化"], "status": "direct", "fact_ids": ["PB"], "note": "软件工作流"}],
               "gaps": [{"id": "rag", "aliases": ["向量RAG", "RAG"], "status": "not_met", "note": "没有完整向量RAG项目实操"},
                        {"id": "platform", "aliases": ["Coze", "Dify"], "status": "not_met", "note": "无平台项目实操记录"},
                        {"id": "LangGraph", "aliases": ["LangGraph"], "status": "unknown", "note": "未找到可核对证据"}],
               "materials": {"headline": "测试候选人｜AI应用实习生", "intro_fact_ids": [], "primary_fact_ids": ["PB"],
                             "required_fact_ids": ["ED", "ROLE"], "skill_fact_ids": ["PY", "SK"], "evidence_fact_ids": ["PB", "SK", "ROLE"], "availability_fact_ids": ["AV"]}}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    return load_candidate(path)


@pytest.fixture
def candidate(tmp_path):
    return make_candidate(tmp_path)


def job(text, **overrides):
    return {"id": "test-job", "role_title": "AI Agent实习生", "company": "测试雇主",
            "jd_raw": text, "verification_status": "employer_verified",
            "official_url": "https://careers.example.invalid/jobs/1", "work_mode": "remote",
            "location": "中国全国", "employment_type": "internship", **overrides}


def categories(result):
    return {c["category"]: c for r in result["R"] for c in r["components"]}


def test_complete_source_offsets_and_compound_obligations(candidate):
    result = assess(job("任职要求\n熟悉Python并有3年商业经验。"), candidate)
    assert result["decision"] == "hold"
    assert all(r["status"] != "direct" for r in result["R"])
    assert categories(result)["experience_years"]["status"] == "unknown"
    verify_requirement_offsets(result, "任职要求\n熟悉Python并有3年商业经验。")


def test_independent_python_not_inferred_from_ai_code(candidate):
    result = assess(job("岗位要求：\n独立熟练Python开发，具备三年经验。"), candidate)
    assert result["decision"] == "hold"
    assert categories(result)["independent_coding"]["status"] == "unknown"
    assert categories(result)["skill:python"]["status"] == "partial"


@pytest.mark.parametrize("quote,status", [("本科及以上在读", "direct"), ("已获得本科学位", "not_met"), ("Bachelor's degree", "not_met"), ("Currently pursuing a bachelor's degree", "direct")])
def test_education_state_not_only_level(candidate, quote, status):
    assert categories(assess(job(quote), candidate))["education"]["status"] == status


def test_degree_or_equivalent_does_not_exclude_enrolled_candidate(candidate):
    result = assess(job("Minimum education: Bachelor’s degree or an equivalent combination of education"), candidate)
    assert categories(result)["education"]["status"] == "unknown"
    assert not result["hard_conflicts"]


@pytest.mark.parametrize("quote", ["2027/2028届", "2027届或2028届", "2027 or 2028 graduates"])
def test_graduation_or(candidate, quote):
    assert categories(assess(job(quote), candidate))["graduation_year"]["status"] == "direct"


def test_title_cohort_gate_and_its_own_offsets(candidate):
    title = "27届AI Agent实习生"
    result = assess(job("任职要求\n了解MCP。", role_title=title), candidate)
    assert result["decision"] == "reject"
    requirement = next(r for r in result["R"] if r["source_field"] == "role_title")
    assert title[requirement["start"]:requirement["end"]] == "27届"
    verify_requirement_offsets(result, "任职要求\n了解MCP。")


def test_negated_experience_and_range_minimum(candidate):
    result = assess(job("无需3年经验，了解MCP。"), candidate)
    assert "experience_years" not in categories(result)
    assert categories(result)["experience_policy"]["status"] == "direct"
    ranged = categories(assess(job("1-5年产品经理经验"), candidate))["experience_years"]
    assert "要求1年" in ranged["reason"] and ranged["status"] == "unknown"


def test_days_are_guaranteed_minimum_not_possible_maximum(candidate):
    assert categories(assess(job("至少每周4天"), candidate))["weekly_availability"]["status"] == "direct"
    assert categories(assess(job("每周5天"), candidate))["weekly_availability"]["status"] == "unknown"
    assert categories(assess(job("每周6天"), candidate))["weekly_availability"]["status"] == "not_met"


def test_start_date_only_required_when_jd_requests(candidate):
    result = assess(job("了解MCP"), candidate)
    assert not any(u["category"] == "start_date" for u in result["U"])
    assert categories(assess(job("要求尽快到岗"), candidate))["start_date"]["status"] == "unknown"


def test_conceptual_knowledge_explicit_practice_gap_and_unknown(candidate):
    assert categories(assess(job("了解RAG概念"), candidate))["gap:rag"]["status"] == "unknown"
    assert categories(assess(job("实做向量RAG项目"), candidate))["gap:rag"]["status"] == "not_met"
    assert categories(assess(job("有LangGraph项目"), candidate))["gap:LangGraph"]["status"] == "unknown"


def test_bonus_section_ends_and_mixed_bonus_line(candidate):
    text = "任职要求\n了解MCP，Coze/Dify经验优先。\n加分项\n有向量RAG项目。\n岗位职责\n构建Agent工作流。\n任职要求\n每周4天。"
    result = assess(job(text), candidate)
    assert [r["priority"] for r in result["R"]] == ["required", "bonus", "bonus", "responsibility", "required"]
    assert not result["hard_conflicts"]
    assert not result["explicit_gaps"]


def test_company_promotions_benefits_excluded_but_schedule_kept(candidate):
    text = "公司介绍：\n我们拥有先进AI Agent\n岗位职责\n开发MCP桥接\n任职要求\n了解MCP\n薪资福利\n工资200元每天\n工作时间：周一至周五\n联系我们\n联系电话12345"
    result = assess(job(text), candidate)
    assert not any("工资" in r["quote"] or "12345" in r["quote"] or "我们拥有" in r["quote"] for r in result["R"])
    assert categories(result)["fixed_weekdays"]["status"] == "unknown"


def test_only_duties_and_fulltime_are_honest_holds(candidate):
    result = assess(job("岗位职责\n负责MCP开发", employment_type="full_time"), candidate)
    assert result["decision"] == "hold"
    assert {u["category"] for u in result["U"]} >= {"qualification_section", "employment_type"}


def test_source_and_closed_are_not_rank_overrides(candidate):
    live = assess(job("了解MCP", verification_status="official_platform_live", official_url=None), candidate)
    assert live["decision"] == "hold"
    closed = assess(job("了解MCP", verification_status="closed"), candidate)
    assert closed["decision"] == "reject"


def test_industrial_automation_is_not_software_workflow(candidate):
    industrial = assess(job("任职要求\nPLC自动化设备装配与机械调试", role_title="自动化助理工程师"), candidate)
    ai = assess(job("了解MCP"), candidate)
    assert industrial["job_family"] == "工业自动化/机械电气"
    assert "skill:workflow" not in categories(industrial)
    assert ai["rank_score"] > industrial["rank_score"]


def test_major_list_with_or_does_not_reject_allowed_major(candidate):
    result = assess(job("计算机、电子信息或相关专业"), candidate)
    assert categories(result)["major"]["status"] == "direct"


def test_loader_rejects_source_drift_and_unapproved_sentence(candidate):
    with pytest.raises(CandidateError, match="批准"):
        approved_text(candidate, "PY", "精通Python并独立实现生产系统")
    path = Path(candidate["_profile_path"])
    source = Path(candidate["facts"][0]["source"]["resolved_path"])
    source.write_text("tampered", encoding="utf-8")
    with pytest.raises(CandidateError, match="变化"):
        load_candidate(path)
