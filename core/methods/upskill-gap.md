---
producer: claude-code
producer_role: foreground-worker
producer_evidence: "2026-08-01 core 大改吸收;自 career-ops jd-skill-gap.mjs/upskill.mjs 与 ai-job-search /upskill 命令提炼"
review_owner: codex-controller
review_state: needs_review
canonical_status: candidate
upstream_source:
  - project: santifer/career-ops
    commit: 93b1cbb
    license: MIT
    files: [jd-skill-gap.mjs, upskill.mjs, skill-extract.mjs]
  - project: MadsLorentzen/ai-job-search
    commit: 1cdaf94
    license: MIT
    command: .claude/commands/upskill.md
absorbed_by: claude-code
method: upskill-gap
---

# 技能缺口统计(upskill-gap)

来源:career-ops `jd-skill-gap.mjs`/`upskill.mjs`/`skill-extract.mjs`(commit `93b1cbb`,MIT)+ ai-job-search `/upskill`(commit `1cdaf94`,MIT)。核心主张:**市场告诉我们学什么,而不是先把整个 CS 本科重新学一遍**。

## 机制

1. **收集**:持续积累目标岗位的 JD(投递 tracker 的 `jd_text_path` 归档天然提供语料);
2. **抽取**:从 JD 文本抽取技能/工具/领域术语(skill-extract 式:关键词 + 上下文判定,而非纯词频);
3. **统计**:按术语出现频率聚合(如 100 个 JD:60 个要求 Python、47 个 API、38 个 n8n/Dify、31 个 SQL、22 个 RAG、8 个算法题、3 个 PyTorch);
4. **对比**:候选档案 `candidate-profile.schema.json` 的 skills 清单做差集 → 缺口清单;
5. **排序**:按"出现频率 × 缺口"排序,输出优先级学习计划(带学习资源)。

## 关键纪律

- **频率不是一切**:要求"Python"的 60 个岗位可能 59 个是把 Python 当默认工具而非核心考核——需结合 JD 中的级别词(熟练/精通/了解)二次判定;
- **不伪造掌握**:缺口就是缺口,学习计划指向"补真技能",不指向"简历加关键词"(后者违背证据优先内核);
- **与 fit framework 联动**:缺口统计喂给 fit framework 的技术匹配维度(weak match areas),评估与学习共用一份数据。

## 输出格式建议

```text
skill_gap: Python 基础(60/100 JD 提及,当前掌握度:可读改,不可独立从零实现)
  priority: high
  evidence: 60 个 JD 中 47 个要求 API 集成,27 个要求测试编写
  plan: [2 周 Python 实战:用现有项目重构一个模块,产出可运行代码与测试]
```

## 与内核的接法

- 数据源:tracker schema 的 `jd_text_path` 归档 + candidate-profile 的 skills;
- 2B 阶段:实现 `upskill-gap` 统计脚本(纯本地,无 LLM 依赖——词频统计不需要模型);
- 输出作用于 self(学习决策)与 service(岗位匹配的缺口分析增强)。
