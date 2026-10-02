"""Conservative, local R/E/U/V matching against a reviewed fact ledger.

R: original requirements with character offsets. E: evidence and limits.
U: unknowns and explicit gaps. V: human verification questions.
Scores sort observations; they never override eligibility or missing evidence.
"""
from __future__ import annotations

import re
from typing import Any

from .candidate import canonical_hash, sha256_bytes

ENGINE_VERSION = "career-match-v1"
CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
NUM = r"(\d+(?:\.\d+)?|[一二两三四五六七八九十])"
QUALIFICATION = re.compile(r"任职|任职资格|岗位要求|职位要求|招聘要求|资格|qualification|requirements|who you are|what you bring", re.I)
DUTY = re.compile(r"职责|工作内容|what you.ll do|responsibilit", re.I)
BONUS = re.compile(r"加分|优先|优先考虑|更佳|preferred|nice.to.have|a plus|bonus", re.I)
OTHER_SECTION = re.compile(r"福利|薪资|待遇|公司介绍|公司简介|企业简介|关于我们|联系我们|投递渠道|申请方式|招聘流程|why.{0,12}(?:join|choose)|benefits|about us|how to apply", re.I)
LOGISTICS_TEXT = re.compile(r"周一.{0,3}周五|无课|全职实习|每周.{0,12}天|到岗|工作时间|实习.{0,12}(?:月|months)|on.?site|visa|work authori", re.I)


def jd_text(job: dict) -> str:
    return str(job.get("jd_raw") or job.get("jd_text") or job.get("description") or job.get("text") or "")


def job_title(job: dict) -> str:
    return str(job.get("role_title") or job.get("title") or "待核验岗位")


def job_id(job: dict) -> str:
    return str(job.get("id") or job.get("observation_id") or job.get("external_id") or canonical_hash(job)[:16])


def _number(value: str) -> float:
    return float(CN_DIGITS[value]) if value in CN_DIGITS else float(value)


def _term_present(term: str, text: str) -> bool:
    """Latin identifiers must be complete tokens (rag must not match 'storage')."""
    if not term:
        return False
    if re.fullmatch(r"[a-zA-Z0-9_.+ /-]+", term):
        return bool(re.search(r"(?<![a-zA-Z0-9_])" + re.escape(term) + r"(?![a-zA-Z0-9_])", text, re.I))
    return term.casefold() in text.casefold()


def _spans(text: str):
    """Split clauses while retaining exact source offsets and inherited section."""
    section = "context" if re.search(r"(?:^|[\n\r])\s*(?:岗位职责|任职要求|任职资格|岗位要求|responsibilities|requirements|qualifications)\s*[:：]?\s*(?:$|[\n\r])", text, re.I) else "required"
    # Chinese full stops delimit sentences; ASCII periods stay inside API names.
    for match in re.finditer(r"[^\n\r;；。!?！？]+", text):
        raw = match.group(0)
        cleaned = re.sub(r"^\s*(?:[-*•]\s*|\d+[.)、]\s*)?", "", raw).rstrip()
        if not cleaned:
            continue
        start = match.start() + raw.find(cleaned)
        if OTHER_SECTION.search(cleaned) and (len(cleaned) < 50 or cleaned.endswith((":", "："))):
            section = "context"
            continue
        heading = cleaned.rstrip(":：").strip().lower()
        if len(cleaned) < 50 and (cleaned.endswith((":", "：")) or heading in {
                "requirements", "qualifications", "responsibilities", "preferred qualifications",
                "任职要求", "岗位要求", "职位要求", "任职资格", "招聘要求", "岗位职责", "职责", "工作内容", "加分项", "优先条件"}):
            if BONUS.search(cleaned):
                section = "bonus"
                continue
            if QUALIFICATION.search(cleaned):
                section = "required"
                continue
            if DUTY.search(cleaned):
                section = "responsibility"
                continue
        # A leading heading in the same sentence changes its interpretation.
        if re.match(r"(?:岗位职责|工作职责|职责|工作内容)[:：]", cleaned):
            section = "responsibility"
        elif re.match(r"(?:任职要求|岗位要求|任职资格|要求)[:：]", cleaned):
            section = "required"
        elif re.match(r"(?:加分项|优先条件|bonus|preferred qualifications)[:：]", cleaned, re.I):
            section = "bonus"
        if section == "context" and not LOGISTICS_TEXT.search(cleaned):
            continue
        local_section = "required" if section == "context" else section
        if local_section == "required" and re.match(r"负责|协助|参与", cleaned) and not QUALIFICATION.search(cleaned):
            local_section = "responsibility"
        # Compound obligations are atomized only where the continuation has its own predicate.
        boundaries = list(re.finditer(r"[，,]|(?:并且|且|以及|同时|\band\b)\s*(?=(?:具备|拥有|有|熟练|熟悉|独立|至少|能|会|\d|proficien|experien|able|independent))", cleaned, re.I))
        chunks = []
        previous = 0
        for boundary in boundaries:
            following = cleaned[boundary.end():].lstrip()
            if boundary.group(0) in {"，", ","} or re.match(r"(?:具备|拥有|有\S|熟练|熟悉|独立|至少|能|会|\d|proficien|experien|able|independent)", following, re.I):
                chunks.append((previous, boundary.start()))
                previous = boundary.end()
        chunks.append((previous, len(cleaned)))
        for left, right in chunks:
            piece = cleaned[left:right]
            quote = piece.strip()
            if quote:
                offset = start + left + len(piece) - len(piece.lstrip())
                priority = "bonus" if BONUS.search(quote) else local_section
                if local_section == "bonus":
                    priority = "bonus"
                yield quote, offset, offset + len(quote), priority, cleaned


def _out(status: str, category: str, reason: str, fact_ids: list[str] | None = None,
         *, hard: bool = False, verification: str = "") -> dict:
    return {"status": status, "category": category, "reason": reason,
            "fact_ids": list(dict.fromkeys(fact_ids or [])), "hard": hard,
            "verification": verification}


def _kind_facts(candidate: dict, kind: str) -> list[str]:
    return [f["id"] for f in candidate.get("facts", []) if f.get("kind") == kind]


def _education_components(quote: str, candidate: dict) -> list[dict]:
    education = candidate.get("identity", {}).get("education", {})
    levels = {"bachelor": 1, "undergraduate": 1, "本科": 1, "master": 2,
              "硕士": 2, "phd": 3, "doctor": 3, "博士": 3}
    level = levels.get(str(education.get("level", "")).lower())
    result = []
    if re.search(r"本科|学士|bachelor|undergraduate|硕士|博士|master.s|ph\.?d", quote, re.I):
        minimum = 3 if re.search(r"博士|ph\.?d", quote, re.I) else 2 if re.search(r"硕士|master.s", quote, re.I) else 1
        # '本科或硕士' permits the lower level.
        if re.search(r"本科.{0,4}(?:或|及|/|、).{0,4}硕士", quote):
            minimum = 1
        if level is None:
            status, reason = "unknown", "候选人学历信息未确认"
        elif level < minimum:
            status, reason = "not_met", "审核学历低于明确的最低学历要求"
        elif (re.search(r"(?:已取得|持有|毕业|获得).{0,8}(?:学位|本科)|earned.{0,8}degree|bachelor.{0,4}degree", quote, re.I)
              and not re.search(r"在读|正在攻读|pursuing|currently enrolled", quote, re.I)
              and education.get("status") == "enrolled"):
            if re.search(r"or.{0,12}equivalent|或.{0,8}(?:同等|等效|相当)", quote, re.I):
                status, reason = "unknown", "已取得学位有等效资格替代条件；在读状态不自动满足或排除等效资格"
            else:
                status, reason = "not_met", "要求已毕业/已取得学位，而候选人仍在读"
        else:
            status, reason = "direct", "审核教育信息符合学历层级；学位状态按原文判断"
        result.append(_out(status, "education", reason, _kind_facts(candidate, "education"), hard=True,
                           verification="核实学校、学历及岗位是否接受在读本科生" if status == "unknown" else ""))
    years = [int(y) for y in re.findall(r"(20\d{2})(?:\s*(?:届|年毕业|毕业生)|\s*graduates?)", quote, re.I)]
    years += [2000 + int(y) for y in re.findall(r"(?<!\d)(2\d)\s*届", quote)]
    if re.search(r"届|毕业|graduates?", quote, re.I) and re.search(r"(?:或|or|/|、)", quote, re.I):
        years = [int(y) for y in re.findall(r"20\d{2}", quote)]
    if years:
        # Also accept the second year of an explicit graduation-year range.
        range_match = re.search(r"(20\d{2})\s*[-~至/、]\s*(20\d{2})\s*届", quote)
        if range_match:
            years = list(range(int(range_match[1]), int(range_match[2]) + 1))
        graduation = education.get("graduation_year")
        status = "unknown" if graduation is None else "direct" if int(graduation) in years else "not_met"
        result.append(_out(status, "graduation_year", f"岗位允许毕业届别 {years}；审核候选人预计毕业年份 {graduation or '未知'}",
                           _kind_facts(candidate, "education"), hard=True,
                           verification="确认预计毕业年份及岗位允许届别" if status == "unknown" else ""))
    if re.search(r"(?:仅限|要求|须|需|必须).{0,6}(?:已毕业|毕业生)|应届毕业生", quote) and not years:
        if education.get("status") == "enrolled":
            result.append(_out("unknown", "graduation_status", "岗位使用应届/毕业生条件，尚不清楚是否接受当前在读实习生",
                               hard=True, verification="请雇主确认2028届在读本科生是否符合"))
    if re.search(r"(?:计算机|软件工程|人工智能|电子信息|相关专业).{0,14}(?:专业|优先)|(?:专业.{0,8}(?:计算机|软件|电子信息))", quote):
        major = str(education.get("major", ""))
        if not major:
            result.append(_out("unknown", "major", "专业信息未知", hard=True, verification="核实接受专业"))
        elif "电子信息" in quote and "电子信息" in major:
            result.append(_out("direct", "major", "原文允许电子信息专业", _kind_facts(candidate, "education"), hard=True))
        elif "相关专业" in quote:
            result.append(_out("partial", "major", "电子信息与岗位可能相关，但相关专业范围需雇主确认",
                               _kind_facts(candidate, "education"), hard=True, verification="雇主是否接受电子信息工程专业"))
        elif any(x in quote and x in major for x in ("计算机", "软件工程", "人工智能")):
            result.append(_out("direct", "major", "专业原文匹配", _kind_facts(candidate, "education"), hard=True))
        else:
            result.append(_out("not_met", "major", "审核专业不在明确限定专业列表中", _kind_facts(candidate, "education"), hard=True))
    return result


def _logistics_components(quote: str, candidate: dict) -> list[dict]:
    availability = candidate.get("availability", {})
    result = []
    days = re.search(r"(?:每周|一周|周出勤|weekly)\D{0,7}" + NUM + r"\s*(?:天|days?)", quote, re.I)
    if days:
        required = _number(days[1])
        minimum = availability.get("days_per_week_min")
        maximum = availability.get("days_per_week_max")
        status = ("unknown" if maximum is None else "not_met" if float(maximum) < required
                  else "unknown" if minimum is None or float(minimum) < required else "direct")
        result.append(_out(status, "weekly_availability", f"要求每周{required:g}天；用户确认范围为{availability.get('days_per_week_min', '?')}-{maximum or '?'}天",
                           _kind_facts(candidate, "availability"), hard=True,
                           verification="确认是否能固定达到岗位要求的每周出勤天数" if status == "unknown" else ""))
    duration = re.search(r"(?:至少|不少于|minimum|实习(?:期|时间)?|持续)\D{0,6}" + NUM + r"\s*(?:个)?(?:月|months?)", quote, re.I)
    if duration:
        required = _number(duration[1])
        months = availability.get("duration_months")
        status = "unknown" if months is None else "direct" if float(months) >= required else "not_met"
        result.append(_out(status, "duration", f"要求至少{required:g}个月；本学期可实习不等于已确认精确月数", hard=True,
                           verification="确认实习结束日期和连续实习月数" if status == "unknown" else ""))
    if re.search(r"无课|全职实习", quote):
        result.append(_out("unknown", "fulltime_intern_schedule", "用户确认4-5天与本学期可参与，未确认无课全职实习安排",
                           _kind_facts(candidate, "availability"), hard=True, verification="确认课程、无课时间与连续全职实习安排"))
    if re.search(r"周一\s*(?:至|到|-|—|~)\s*周五", quote):
        minimum = availability.get("days_per_week_min")
        status = "direct" if minimum is not None and float(minimum) >= 5 else "unknown"
        result.append(_out(status, "fixed_weekdays", "岗位为周一至周五固定工作时间；每周4-5天尚不能证明可固定5天",
                           _kind_facts(candidate, "availability"), hard=True, verification="确认周一至周五固定时间、课程冲突与到场安排" if status == "unknown" else ""))
    if re.search(r"立即|尽快|一周内|两周内|到岗|入职日期|start date|immediate", quote, re.I):
        start = availability.get("start_date")
        result.append(_out("unknown", "start_date", "岗位要求具体到岗时间，候选人起始日期尚未确认" if not start else "已提供候选人到岗日，但需与岗位时间窗口核对",
                           hard=True, verification="确认双方最早到岗日期和岗位截止时间"))
    if re.search(r"现场|线下|坐班|到办公室|onsite|on-site|office.based|hybrid", quote, re.I):
        if availability.get("remote_only") is True:
            result.append(_out("not_met", "work_mode", "明确到场要求与用户remote-only约束冲突", hard=True))
        else:
            result.append(_out("unknown", "work_mode", "远程优先不是拒绝线下；候选人到场/通勤安排未确认", hard=True,
                               verification="确认办公地址、到场频次及可行通勤/住宿"))
    if re.search(r"(?:必须|要求|须|需|only|required).{0,20}(?:工作许可|工作签证|国籍|citizen|work authori|right to work|visa)|(?:work authori|right to work)", quote, re.I):
        result.append(_out("unknown", "work_authorization", "尚未确认工作许可或国籍资格", hard=True,
                           verification="核实该地区工作许可及雇主接受范围"))
    return result


def _skill_components(quote: str, candidate: dict) -> list[dict]:
    components = []
    caps = [c for c in candidate.get("capabilities", [])
            if any(_term_present(str(alias), quote) for alias in c.get("aliases", []))]
    if re.search(r"PLC|电气|机械|装配|机电|非标|设备|车间|气动|仪表", quote, re.I) and not re.search(r"Agent|MCP|软件工作流|AI应用|AI 应用", quote, re.I):
        caps = [c for c in caps if c.get("id") != "workflow"]
    gaps = [g for g in candidate.get("gaps", [])
            if any(_term_present(str(alias), quote) for alias in g.get("aliases", []))]
    # A gap may describe missing complete project practice, not absent conceptual knowledge.
    practice_required = bool(re.search(r"搭建|构建|开发|落地|项目|实践|实操|production|build|implement|hands.on|experience", quote, re.I))
    for cap in caps:
        status = cap["status"]
        reason = cap.get("note") or "审核能力证据"
        advanced = bool(re.search(r"熟练|精通|独立|专家|proficien|expert|independent|strong command|advanced", quote, re.I))
        verified_scope = str(cap.get("level", ""))
        if status == "direct" and advanced and verified_scope not in {"proficient", "expert", "independent"}:
            status = "partial"
            reason += "；已有任务实践不能直接证明熟练、精通或独立实现"
        components.append(_out(status, f"skill:{cap['id']}", reason, cap.get("fact_ids", []),
                               verification="通过实际任务/面试验证要求的熟练程度与独立实现能力" if status in {"partial", "unknown"} else ""))
    for gap in gaps:
        # The controller can limit an explicit gap to complete-project experience.
        scoped = gap.get("scope", "project_practice")
        status = gap["status"] if practice_required or scoped == "all" else "unknown"
        components.append(_out(status, f"gap:{gap.get('id', 'unrecorded')}",
                               gap.get("note", "没有经过审核的此项证据") + ("；原文只要求了解概念，不推导为完全不懂" if status == "unknown" and gap["status"] == "not_met" else ""),
                               verification="确认具体概念掌握程度或补充真实作品" if status == "unknown" else ""))
    if re.search(r"(?:独立|手写|不依赖AI|without AI|independent).{0,14}(?:Python|编程|编码|开发)|(?:Python).{0,14}(?:独立|手写)", quote, re.I):
        independent = candidate.get("constraints", {}).get("independent_python")
        status = "direct" if independent is True else "not_met" if independent is False else "unknown"
        components.append(_out(status, "independent_coding", "真实审核角色为AI协作需求、规则、调试、验收；独立编码能力须另行验证",
                               _kind_facts(candidate, "role"), verification="用不依赖AI的实际题目验证独立编码能力" if status == "unknown" else ""))
    # Extra obligations must not disappear just because one known technology occurs.
    known_tools = ("SQL", "Java", "JavaScript", "TypeScript", "C++", "Go", "Rust", "Docker", "Kubernetes", "Linux", "PyTorch", "TensorFlow", "HuggingFace", "React", "Vue", "AWS", "Azure", "GCP", "LLM", "RAG", "LlamaIndex", "Function Calling", "Office", "RPA", "SCRM", "PLC", "Codesys", "HMI", "PR", "AE", "PS", "剪映", "视频制作", "视频剪辑", "营销平台", "英语", "英文", "数据结构", "算法", "机器学习", "深度学习")
    for tool in known_tools:
        if _term_present(tool, quote) and not any(any(_term_present(str(a), tool) or _term_present(tool, str(a)) for a in cap.get("aliases", [])) for cap in caps):
            components.append(_out("unknown", f"unrecorded:{tool}", f"没有已审核的{tool}能力证据；不等于用户不具备",
                                   verification=f"补充真实{tool}作品或面试验证"))
    scope_checks = (("production_scope", r"生产部署|高并发|百万|大规模|分布式|生产级|SLA|production deployment|at scale|high.volume", "企业规模、生产部署或性能能力"),
                    ("commercial_scope", r"商业(?:项目|经验)|客户交付|enterprise|commercial", "商业项目或客户交付经历"))
    for category, pattern, label in scope_checks:
        if caps and re.search(pattern, quote, re.I):
            components.append(_out("unknown", category, f"个人项目的{caps[0]['id']}证据不能单独证明{label}",
                                   verification=f"核验真实{label}与岗位期望的规模"))
    return components


def _components(quote: str, candidate: dict) -> list[dict]:
    components = _education_components(quote, candidate) + _logistics_components(quote, candidate)
    no_experience = bool(re.search(r"无需.{0,8}(?:经验|工作)|不(?:需要|要求).{0,8}(?:经验|工作)|不限经验|无经验要求|no experience required", quote, re.I))
    exp_range = re.search(NUM + r"\s*[-~至—]\s*" + NUM + r"\s*(?:年|years?).{0,14}(?:经验|工作|experience)", quote, re.I)
    experience = None if no_experience else re.search(NUM + r"\s*(?:年|years?).{0,12}(?:经验|工作|experience)|(?:经验|工作经验|experience).{0,8}" + NUM + r"\s*(?:年|years?)", quote, re.I)
    if experience:
        required = _number(exp_range[1]) if exp_range else _number(experience[1] or experience[2])
        actual = candidate.get("constraints", {}).get("experience_years")
        status = "unknown" if actual is None else "direct" if float(actual) >= required else "not_met"
        components.append(_out(status, "experience_years", f"要求{required:g}年经验；审核可核对年限为{actual if actual is not None else '未知'}",
                               hard=True, verification="核对经历起止与雇主接受的经验定义" if status == "unknown" else ""))
    if no_experience:
        components.append(_out("direct", "experience_policy", "原文明确无需既有工作经验", hard=True))
    components += _skill_components(quote, candidate)
    return components or [_out("unknown", "unclassified", "此句不能从审核事实自动验证；保留原文供人工判断",
                               verification="逐句核实该岗位条件与候选人真实经历")]


def extract_requirements(job: dict) -> list[dict]:
    text = jd_text(job)
    requirements = [{"id": f"R{index:03d}", "quote": quote, "start": start, "end": end,
             "priority": priority, "source_sentence": sentence, "source_field": "jd_raw"}
            for index, (quote, start, end, priority, sentence) in enumerate(_spans(text), 1)]
    title = job_title(job)
    for match in re.finditer(r"(?:20\d{2}|2\d)(?:\s*(?:[/、或-]\s*)?(?:20\d{2}|2\d))?\s*届", title):
        requirements.append({"id": f"R{len(requirements) + 1:03d}", "quote": match[0],
                             "start": match.start(), "end": match.end(), "priority": "required",
                             "source_sentence": title, "source_field": "role_title"})
    return requirements


def _overall(components: list[dict]) -> str:
    statuses = {c["status"] for c in components}
    if statuses == {"direct"}:
        return "direct"
    if statuses == {"not_met"}:
        return "not_met"
    if statuses == {"unknown"}:
        return "unknown"
    # Mixed complete + missing requirements cannot be declared fully supported.
    return "partial"


def assess(job_or_observation: dict, candidate: dict) -> dict:
    job = dict(job_or_observation)
    text = jd_text(job)
    actual_jd_hash = sha256_bytes(text.encode("utf-8"))
    requirements = extract_requirements(job)
    conflicts, unknown, risk, verification = [], [], [], []
    evidence = []
    for requirement in requirements:
        components = _components(requirement["quote"], candidate)
        requirement["components"] = components
        requirement["status"] = _overall(components)
        requirement["fact_ids"] = list(dict.fromkeys(f for c in components for f in c["fact_ids"]))
        required = requirement["priority"] == "required"
        hard_components = [c for c in components if c["hard"]]
        requirement["hard"] = required and bool(hard_components)
        for component in components:
            entry = {"requirement_id": requirement["id"], "quote": requirement["quote"],
                     "start": requirement["start"], "end": requirement["end"], **component}
            evidence.append(entry)
            if required and component["status"] == "not_met":
                if component["hard"]:
                    conflicts.append(entry)
                else:
                    risk.append(f"{requirement['id']} 必选能力存在明确实践缺口：{component['reason']}")
            if required and component["status"] in {"unknown", "partial"}:
                unknown.append(entry)
            if component.get("verification"):
                verification.append({"requirement_id": requirement["id"], "question": component["verification"],
                                     "reason": component["reason"], "required": required})
    source_status = job.get("verification_status")
    employer_verified = source_status == "employer_verified" or job.get("application_verified") is True
    if source_status is None:
        employer_verified = job.get("source_verified") is True and bool(job.get("official_apply_url") or job.get("official_url"))
    closed = source_status == "closed" or str(job.get("status", "")).lower() in {"closed", "expired", "filled"}
    if closed:
        conflicts.append({"category": "closed", "status": "not_met", "hard": True,
                          "reason": "来源明确岗位已关闭", "requirement_id": None})
    if not text.strip():
        unknown.append({"category": "jd_text", "status": "unknown", "reason": "缺少完整JD原文", "hard": True})
    if text.strip() and not any(r["priority"] == "required" and r.get("source_field") == "jd_raw" for r in requirements):
        unknown.append({"category": "qualification_section", "status": "unknown", "reason": "JD只有职责/说明，任职资格信息不足，需雇主补充", "hard": True})
    if job.get("jd_hash") and job["jd_hash"] != actual_jd_hash:
        unknown.append({"category": "jd_hash", "status": "unknown", "reason": "JD哈希与原文不一致", "hard": True})
        risk.append("JD快照完整性校验失败")
    if not employer_verified and not closed:
        unknown.append({"category": "source_verification", "status": "unknown", "hard": True,
                        "reason": "官方平台在线记录不能替代雇主及真实投递通道核验" if source_status == "official_platform_live" else "岗位来源、雇主或官方申请入口尚未核验"})
        verification.append({"requirement_id": None, "question": "核实雇主身份、岗位仍开放及官方申请入口", "required": True})
    apply_url = job.get("official_apply_url") or job.get("official_url")
    if employer_verified and not apply_url:
        unknown.append({"category": "apply_url", "status": "unknown", "hard": True, "reason": "缺少经过核验的官方申请URL"})
    # Structured location/work mode is still an eligibility condition, even when absent from prose.
    work_mode = str(job.get("work_mode") or "").lower()
    location = str(job.get("location") or "")
    if not work_mode or work_mode in {"unknown", "unspecified", "待核验"}:
        unknown.append({"category": "work_mode", "status": "unknown", "hard": True, "reason": "远程/混合/到场要求未知"})
    elif work_mode in {"onsite", "on-site", "hybrid", "线下", "现场", "混合"}:
        existing = any(u.get("category") == "work_mode" for u in unknown)
        if not existing and not conflicts:
            unknown.append({"category": "work_mode", "status": "unknown", "hard": True,
                            "reason": f"工作地点{location or '未知'}要求到场；用户远程优先但线下安排未确认"})
    if work_mode in {"remote", "远程"} and location and not re.search(r"广东|中国|全国|不限|anywhere|worldwide|global", location, re.I):
        unknown.append({"category": "remote_location", "status": "unknown", "hard": True,
                        "reason": f"远程岗位标注地区{location}，尚未确认能否从广东工作及工作许可"})
    employment = str(job.get("employment_type") or "").casefold().replace("-", "_").replace(" ", "_")
    if employment in {"full_time", "fulltime", "全职", "正式", "permanent"}:
        unknown.append({"category": "employment_type", "status": "unknown", "hard": True,
                        "reason": "结构化岗位类型为正式全职，与候选人在读实习/兼职目标不同，须确认岗位是否接受实习安排"})
        verification.append({"requirement_id": None, "question": "确认全职招聘是否可转为在读实习或兼职", "required": True})
    risk += [str(r) for r in job.get("risk_flags", [])]
    # Titles describe interest alignment only; a high family score cannot pass a hard rule.
    title = job_title(job)
    families = [("工业自动化/机械电气", r"PLC|电控|电气|配电|设备|机械|机电|锂电|装配|车间|仪表|工厂"),
                ("AI工作流/Agent应用", r"agent|AI.?应用|AI.?工具|工作流|MCP|AI operations"),
                ("AI营销/内容/运营", r"AI.{0,12}(?:营销|内容|视频|数据标注|训练师)|(?:运营|产品|市场).{0,12}AI"),
                ("产品/运营", r"产品|运营|product|operation"),
                ("软件工程", r"开发|工程师|engineer|developer|software"),
                ("算法/研究", r"算法|研究|research|scientist|machine learning")]
    family = next((name for name, pattern in families if re.search(pattern, title, re.I)), "其他/待人工判断")
    if "自动化" in title and re.search(r"PLC|电气|机械|装配|机电|非标|车间|气动|仪表|配电", text, re.I) and not re.search(r"Agent|MCP|软件工作流|AI应用|AI 应用", title, re.I):
        family = "工业自动化/机械电气"
    if re.search(r"AI.{0,12}(?:视频|短剧|内容|数据标注|训练师)", title, re.I):
        family = "AI营销/内容/运营"
    required = [r for r in requirements if r["priority"] == "required"]
    bonus = [r for r in requirements if r["priority"] == "bonus"]
    weights = {"direct": 1.0, "partial": 0.35, "unknown": 0.0, "not_met": 0.0}
    technical = [r for r in required if any(c["category"].startswith(("skill:", "gap:", "unrecorded:")) for c in r["components"])]
    duty_technical = [r for r in requirements if r["priority"] == "responsibility" and r["fact_ids"]]
    coverage = sum(weights[r["status"]] for r in technical) / max(len(technical), 1)
    direction = {"AI工作流/Agent应用": 50, "AI营销/内容/运营": 34, "产品/运营": 25,
                 "软件工程": 20, "算法/研究": 5, "工业自动化/机械电气": -30}.get(family, 5)
    if family == "AI营销/内容/运营":
        direction = (38 if "咨询" in title and re.search(r"工作流|知识库|AI.{0,6}工具", text)
                     else 15 if re.search(r"运营|训练师|标注", title) else 8)
    internship = job.get("employment_type") == "internship" or "实习" in title or "intern" in title.lower()
    employment_score = 20 if internship else -10 if employment in {"full_time", "fulltime", "全职", "permanent"} else 0
    location_score = 10 if work_mode in {"remote", "远程"} else 7 if re.search(r"广东|广州|深圳|佛山|东莞|珠海|江门|惠州", location) else 0
    support_score = round(coverage * 15 + min(5, len(duty_technical)), 1)
    missing_technical = sum(1 for r in technical if any(c["status"] == "not_met" for c in r["components"]))
    penalty = min(20, len([c for c in conflicts if c.get("hard")]) * 15 + missing_technical * 2)
    score = round(max(0, direction + employment_score + location_score + support_score - penalty), 1)
    sorting_factors = {"direction": direction, "internship_fit": employment_score,
                       "location_preference": location_score, "reviewed_evidence_support": support_score,
                       "hard_conflict_penalty": -penalty}
    explicit_gaps = [e for e in evidence if e["status"] == "not_met" and any(r["id"] == e["requirement_id"] and r["priority"] == "required" for r in requirements)]
    if conflicts:
        decision, eligibility = "reject", "not_eligible"
    elif unknown or explicit_gaps:
        decision, eligibility = "hold", "needs_verification"
    else:
        decision, eligibility = "suggested_shortlist", "eligible_for_review"
    reasons = []
    direct = [r for r in requirements if r["status"] == "direct" and r["fact_ids"]]
    for requirement in direct[:3]:
        reasons.append(f"{requirement['id']} 可由审核事实 {', '.join(requirement['fact_ids'])} 直接支持：{requirement['quote']}")
    if not reasons:
        reasons.append("尚未找到足以直接支持岗位要求的审核事实；岗位大类仅用于排序")
    if family == "AI工作流/Agent应用":
        reasons.insert(0, "岗位任务方向接近真实Agent/工作流项目，建议优先人工核对具体技能和实习条件")
    elif family == "AI营销/内容/运营":
        reasons.insert(0, "存在AI工具与业务流程交集；营销/内容专业要求须独立核验")
    if internship:
        reasons.append("岗位明确含实习安排，符合本轮主要投递类型")
    if location_score:
        reasons.append("地点更接近广东/远程偏好；可行通勤或地域限制仍须核验")
    return {"schema_version": "career-assessment-v1", "engine_version": ENGINE_VERSION,
            "job_id": job_id(job), "job_title": title, "jd_hash": actual_jd_hash,
            "candidate_hash": candidate.get("candidate_hash"), "decision": decision,
            "eligibility_status": eligibility, "hard_conflicts": conflicts,
            "unknown_required": unknown, "explicit_gaps": explicit_gaps,
            "requirements": requirements, "R": requirements, "E": evidence,
            "U": unknown + explicit_gaps, "V": verification,
            "required_requirements": required, "bonus_requirements": bonus,
            "rank_score": score, "job_family": family,
            "ranking_factors": sorting_factors,
            "suggested_review_priority": "high" if score >= 50 else "medium" if score >= 20 else "low",
            "recommendation_reasons": reasons, "risk_notes": list(dict.fromkeys(risk)),
            "scoring_boundary": "职业大类与基础分只辅助排序；未知条件、缺口与硬冲突由单独规则裁决"}


def verify_requirement_offsets(assessment: dict, text: str) -> None:
    if assessment.get("jd_hash") != sha256_bytes(text.encode("utf-8")):
        raise ValueError("评估与JD原文哈希不一致")
    for requirement in assessment.get("requirements", []):
        source = assessment.get("job_title", "") if requirement.get("source_field") == "role_title" else text
        if source[requirement["start"]:requirement["end"]] != requirement["quote"]:
            raise ValueError(f"要求原文offset不一致：{requirement['id']}")
