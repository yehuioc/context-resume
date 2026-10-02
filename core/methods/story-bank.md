---
producer: claude-code
producer_role: foreground-worker
producer_evidence: "2026-08-01 core 大改吸收;自 career-ops README/Auto-Pipeline 描述与 STAR 结构提炼(原文散布于 modes/apply.md、interview-prep/,无单一文件)"
review_owner: codex-controller
review_state: needs_review
canonical_status: candidate
upstream_source:
  project: santifer/career-ops
  commit: 93b1cbb
  license: MIT
  note: "Interview Story Bank 为 career-ops 核心 feature;本文档为方法提炼,引用原文见 upstream README Features 与 modes/interview.md"
absorbed_by: claude-code
method: story-bank
---

# Interview Story Bank(面试故事库)

来源:career-ops Interview Story Bank 机制提炼(commit `93b1cbb`,MIT)。核心主张:**5-10 个主故事覆盖所有行为面试问题**——不按问题背答案,按"素材"回答问题。

## 机制

每次岗位评估/面试准备时,把候选人的真实经历沉淀为 **STAR+Reflection 故事**:

- **S**(Situation):情境——当时的背景与约束;
- **T**(Task):任务——你负责的部分;
- **A**(Action):行动——你具体做了什么(本人/AI 协作边界如实);
- **R**(Result):结果——可验证的产出(数字、测试通过、真实使用反馈);
- **Reflection**:反思——你判断了什么、下次怎么做(展示成长,是区分"背故事"与"真做过"的关键)。

故事按"能力标签"索引(如:故障修复、需求拆解、自动化验收、跨工具集成),一个故事可复用回答多个行为问题。

## 为什么是 5-10 个

- 面试官追问的是**细节一致性**——故事库保证每次回答同一个项目的版本一致(防止紧张时自相矛盾);
- 5-10 个主故事覆盖 80%+ 行为问题(团队协作/冲突/失败/成长/主动性/技术深度);
- 故事库随评估积累:每次评估新岗位都在补强故事,而不是从零准备。

## 沉淀格式建议(与 tracker/evidence 对齐)

```text
story_id: ST01
label: 跨日命名缺陷修复(Telegram 日报 Bot)
capabilities: [故障复现, 规则重构, 真实数据验收]
star:
  situation: 7 月真实使用中日报按处理日而非复盘日归档
  task: 复现并定义"按被复盘日期归档"规则
  action: 用真实数据复测;本人定义规则与验收,AI 协作实现
  result: 修复后 29 项自动化测试覆盖日期边界,持续运行无复发
  reflection: 缺陷必须先在真实数据上复现,再改规则——不能靠猜
evidence_refs: [E1, E3]
source_project: P01
```

## 与内核的接法

- 故事库数据落 `self/`(客户 0 号先行)与 `service/`(客户故事库,交付后 7 天删除);
- `evidence_refs` 必须指向 evidence-pack 的已确认证据(防编造硬门与内核一致);
- 2B 阶段:面试准备组件按 story-bank 索引生成"行为问题→候选故事"映射表,作为面试防守包的引擎。
