---
producer: claude-code
producer_role: foreground-worker
producer_evidence: "2026-08-01 core 大改吸收;自 career-ops modes/oferta.md 提炼"
review_owner: codex-controller
review_state: needs_review
canonical_status: candidate
upstream_source:
  project: santifer/career-ops
  commit: 93b1cbb
  license: MIT
  file: modes/oferta.md(Full A-G Evaluation)
absorbed_by: claude-code
method: a-g-evaluation
---

# A-G 岗位评估(吸收 career-ops)

来源:career-ops `modes/oferta.md`(commit `93b1cbb`,MIT)提炼。完整原文见 `../upstream/career-ops/modes/oferta.md`,本文档是吸收后的可执行方法。

## 前置门(评估前必须通过)

1. **Liveness gate**:粘贴 URL 时先确认岗位仍在线——404/过期页面绝不允许进入评估(否则在幻影内容上白费一次完整评估);已关闭岗位直接停止,标记 tracker 为失效。
2. **Blacklist gate**:若存在自己的"不投名单"(data/blacklist.md),先查公司名(大小写/标点不敏感匹配);命中则停止并展示候选人自己记录的决策,等明确回答——**永不静默拒绝、永不静默放行**。
3. **Bounded Research Budget**:限定的研究预算,防止评估无限发散。

## Step 0 — Archetype Detection

先判定 JD 属于哪个岗位画像(archetype:primary/secondary/adjacent),再按画像打分。

## Block A — Role Summary(岗位总结)

- 一句话岗位总结(做什么、招谁);
- **Geo-mismatch check**:工作地点与候选人所在地矛盾时,在报告 Block B 顶部加一行旗帜,引原文证据(绝不转述);
- **Work-authorization check**:签证/工作权硬检查——⛔ 时同样在 Block B 顶部加旗帜,引原文。

## Block B — Match with CV(与简历匹配)

逐条对齐岗位要求与候选人证据,标出匹配/部分/缺口。

## Block C — Level and Strategy(级别与策略)

该岗位实际期望的职级,以及投递策略(平级/上探/降级争取)。

## Block D — Comp and Demand(薪酬与需求)

薪酬研究 + 岗位真实需求度(是否长期缺人、市场热度),为后续谈判提供依据。

## Block E — Customization Plan(定制计划)

CV/材料具体怎么改(哪个项目前置、哪些措辞对齐 JD 关键词)。

## Block F — Interview Plan(面试计划)

面试准备要点:可能的追问、STAR 素材映射。

## Block G — Posting Legitimacy(岗位真实性,防骗)

按顺序分析信号(超出研究预算时只做免费信号):
1. 岗位重复/幽灵岗位(同一岗位反复重发);
2. 公司招聘信号(是否真实在招、团队规模);
3. 第三方平台位置 vs 雇主官网位置矛盾(仅当两者可确认指向同一 req ID);
4. **AI-Buzzword vs Infrastructure Mismatch**:JD 堆 AI 流行词但基础设施描述不匹配;
5. 机构/中介许可检查(有官方注册表的司法辖区,一次查询即可验证运营者资质——无证中介多为幽灵岗位/收费诈骗/错误分类);
6. 其他零成本信号。

## 输出格式

报告含:**URL** + **Legitimacy 分级** + A-G 各块 + 旗帜行(引原文)。评估结果是"投/不投/带条件投"的人工在环决策依据,系统永不自动提交。

## 与内核的接法

- A-G 评估是"评估层"主方法(core 求职系统阶段);Block G 可作为 service 99 元档"目标岗位包"的增值检查;
- Geo/Work-auth 检查在本土(国内求职)映射为:岗位城市 vs 投递距离、学历/年级门槛硬检查;
- 输出字段与 `schema/evidence-pack.schema.json` 的 `jd_matches` 对齐(requirement/evidence/status/action)。
