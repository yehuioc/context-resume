---
producer: claude-code
producer_role: foreground-worker
producer_evidence: "2026-08-01 core 大改吸收;自 resume-matcher ats.py 权重与 prompts/templates.py 提示词约束提炼"
review_owner: codex-controller
review_state: needs_review
canonical_status: candidate
upstream_source:
  project: srbhr/Resume-Matcher
  commit: 116f9cc
  license: Apache-2.0
  files:
    - apps/backend/app/services/ats.py
    - apps/backend/app/prompts/templates.py
absorbed_by: claude-code
license_note: "Apache-2.0 素材;复用须保留版权声明与 NOTICE。"
method: jd-tailoring
---

# JD 裁剪与匹配评分(吸收 Resume-Matcher)

来源:resume-matcher(commit `116f9cc`,Apache-2.0)`ats.py` 三因子评分与 `prompts/templates.py` 的 LLM 输出约束。机制:Master Resume 按目标 JD 重新取材,产出定制简历。

## 三因子匹配评分(ats.py 权重,直接采用)

总分 = 加权三因子,全部可本地计算(无需 LLM):

| 因子 | 权重 | 计算方式 |
|---|---|---|
| keyword_match(关键词匹配率) | **0.55** | 简历文本与 JD 关键词的命中百分比(refinement pipeline 输出) |
| skills_coverage(技能覆盖) | **0.25** | 简历技能清单与 JD 要求技能的重叠度 |
| section_completeness(章节完整) | **0.20** | 必需简历章节是否存在(本地规则,无 LLM) |

**为什么这个权重结构有效**:关键词占比过半(ATS 现实:机器先按关键词筛),技能覆盖次之,章节完整性是基础门槛。评分用于"这岗值不值得投/需要改到什么程度"的决策,不是绝对真理。

## LLM 输出 schema 约束(RESUME_SCHEMA_EXAMPLE,直接采用)

让 LLM 生成结构化简历时,给出**固定 schema 示例**约束输出(而非自由文本)。核心结构:

```json
{
  "personalInfo": { "name": "...", "title": "...", "email": "...", "phone": "...", "location": "...", "website": "...", "linkedin": "...", "github": "..." },
  "summary": "职业概述(按 JD 重写)",
  "workExperience": [ { "id": 1, "title": "...", "company": "...", "location": "...", "years": "Jan 2020 - Present", "description": ["bullet1", "bullet2"], "descriptionStyles": ["bullet", "bullet"] } ],
  "education": [ { "id": 1, "institution": "...", "degree": "...", "years": "...", "description": "..." } ],
  "personalProjects": [ { "id": 1, "name": "...", "role": "...", "years": "...", "description": ["..."], "descriptionStyles": ["bullet"] } ],
  "additional": { "technicalSkills": ["Python", "..."], ... }
}
```

要点:每个描述条目配 `descriptionStyles`(bullet/paragraph),让渲染层知道每行呈现形态;数据与样式分离——与我们内核"schema JSON 唯一事实结构"一致。

## 裁剪流程(六步,吸收自 README How It Works)

1. 上传 Master Resume(全量经历档案);
2. 粘贴目标 JD;
3. AI 生成改进与定制内容(对齐 JD 关键词、相关经历前置);
4. 生成 Cover Letter 与面试准备;
5. 用户自定义布局/章节;
6. 按模板导出 PDF。

## 与内核的接法

- **评分引擎**:三因子权重逻辑是 2B 阶段"JD 匹配脚本"的直接实现依据;`jd_matches` 的 `status`(matched/partial/gap)可由 skills_coverage 细化;
- **提示词约束**:RESUME_SCHEMA_EXAMPLE 结构可直接并入 `service/operations/生成提示词.md` 的进阶版(客户目标岗位包档);
- **与 evidence-pack 关系**:evidence-pack 的 resume_bullets 是"素材",jd-tailoring 产出的是"按 JD 定稿的简历结构"——素材→定稿是 2B 生成器扩展方向;
- **许可**:Apache-2.0 允许复用;引用本方法时保留本 frontmatter 来源标注。
