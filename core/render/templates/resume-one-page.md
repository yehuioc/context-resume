---
producer: claude-code
producer_role: foreground-worker
producer_evidence: "2026-08-01 core 大改吸收;基于 lapis-cv template-cn 形态与 sb2nov 一页结构理念生成"
review_owner: codex-controller
review_state: needs_review
canonical_status: candidate
upstream_source:
  - project: BingyanStudio/LapisCV
    commit: c8ff9e0
    license: MIT
    file: templates/obsidian/template-cn.md(形态参考)
  - project: sb2nov/resume
    commit: 6d0b621
    license: MIT
    note: "single-page one-column 结构理念"
absorbed_by: claude-code
template: resume-one-page
---

# {姓名} | {岗位定位}

> <span class="icon">&#xe60f;</span> `{电话}` <span>&emsp;</span> <span class="icon">&#xe7ca;</span> `{邮箱}` <span>&emsp;</span> <span class="icon">&#xe600;</span> [{GitHub}]({github_url}) <span>&emsp;</span> {所在地} · {最早到岗} · {每周可实习}

## 个人概述

{2-3 句:能力定位 + AI 协作方式 + 证据优先声明。示例:持续将个人真实需求拆解为可运行的 AI Agent 与业务自动化系统;本人负责需求、规则、验收与缺陷修复,代码实现与 Claude Code/Codex 协作完成,全部成果有本地证据可追溯。}

## 项目经历

### {项目名(陌生人可读,不用内部代号)} | {角色} | {时间}
**{一句话价值}**

- **{核心成果,带可验证数字}** — {证据描述,如:29 项自动化测试通过、真实使用 30+ 天无复发}(证据:{证据位置})
- **{技术要点}** — {实现方式,诚实标注 AI 协作}
- **{责任边界}** — 本人负责{需求/规则/验收/缺陷复现},AI 协作实现{部分}

### {第二项目}

- ...

## 教育背景

{学校} · {专业} | {年份}

## 技能与工具

- **核心能力:** {3-5 项,与目标 JD 对齐}
- **工具:** {平台/API/模型,如:飞书 OpenAPI、Telegram Bot API、DeepSeek API、Codex、Claude Code}

---
**使用说明(本行渲染时删除)**:一页投递版只保留与目标岗位最相关的 2-3 个 A/B 级项目;C 级项目一律不写;所有数字必须有证据(测试/日志/真实使用),无证据的写"待补证据"也不许编;AI 协作方式在个人概述统一声明,不在每个项目重复道歉。投递前对照目标 JD 的关键词检查命中率。
