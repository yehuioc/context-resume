---
producer: claude-code
producer_role: foreground-worker
producer_evidence: "2026-08-01 core 大改吸收;完整版简历骨架,供 Master Resume 与客户完整交付包使用"
review_owner: codex-controller
review_state: needs_review
canonical_status: candidate
upstream_source:
  - project: BingyanStudio/LapisCV
    commit: c8ff9e0
    license: MIT
    file: templates/obsidian/template-cn.md(形态参考)
absorbed_by: claude-code
template: resume-full
---

# {姓名} | {岗位定位}

> <span class="icon">&#xe60f;</span> `{电话}` <span>&emsp;</span> <span class="icon">&#xe7ca;</span> `{邮箱}` <span>&emsp;</span> <span class="icon">&#xe600;</span> [{GitHub}]({github_url}) <span>&emsp;</span> {所在地} · {最早到岗} · {每周可实习}

## 个人概述

{能力定位 + AI 协作方式 + 证据优先声明}

## 项目经历

### {项目一} | {角色} | {时间}

**背景**:{项目解决什么问题}

**我的职责**:{需求/规则/验收/缺陷修复(AI 协作如实标注)}

**结果**:{可验证产出:测试、真实使用、数据}

**证据位置**:{本地路径或测试报告}

**面试追问预备**:
- {可能的追问 1}:{诚实答案要点}
- {可能的追问 2}:{诚实答案要点}

### {项目二}

...

## 教育背景

{学校} · {专业} | {年份}

## 技能与工具

- **核心能力:** ...
- **工具:** ...

## 作品与演示(有真实链接才填)

- {可演示项目 1}:{说明}

## 风险提示(内部版,投递前删除)

- {尚缺证据的事项}
- {不能承诺的事项}
- {9 月返校等时间约束}

---
**使用说明(本行渲染时删除)**:完整版用于 Master Resume 与客户完整交付;投递版从本版裁剪;内部风险提示段落投递前必须删除。
