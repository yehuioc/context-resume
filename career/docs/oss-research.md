# 求职开源项目调研与取舍

存储位置：本项目 `docs/oss-research.md`。

结论：复用公开岗位接口与已验证的数据模型思路，在现有候选人事实库上实现本地执行层。没有一个已核查项目能直接满足“国内来源、个人事实权威、逐条证据、人工批准、完整反馈”的全部边界。v0.1 不安装这些上游系统，也不接入它们的账号、浏览器或模型服务。

## 核查范围与可信度

2026-09-30 通过 GitHub API 读取指定十个地址的仓库信息、提交、递归文件树，按固定提交保存 README 与现有 LICENSE。许可证、更新时间和路径来自当日返回；下面的产品功能以固定提交的说明及所注明源码为依据，未运行上游完整产品，不能解释为十套产品全部实测通过。活跃度采用最近 push 日期，不用星数代替工程判断。

公开来源与固定提交登记见 `examples/oss-registry.json`。`scripts/research_oss.py` 保存只读参考快照，不执行上游源码；本机既有来源可以通过私有配置继续读取。

## 功能与复用矩阵

| 项目与固定提交 | 许可证 / 最近 push | 来源与发现 | 匹配、材料 | 投递与状态 | 本轮取舍与风险 |
|---|---|---|---|---|---|
| [freehire](https://github.com/strelov1/freehire/tree/900408d7e3172193966064f096b4dbf4e5d78b2a) | MIT / 2026-09-28 | 多 ATS、公司页与聚合源；公开 HTTP API | 确定性匹配、可选模型分析、经历证据与 CV 编辑 | 申请看板、邮件关联、追加事件；浏览器扩展辅助填表 | **参考并适配设计**：统一 source 接口、公司 board、机会与来源分离。Go/Postgres/Meilisearch/Redis/S3 完整部署超出本地 v0.1 所需；上游宣称的岗位数量与“无失效链接”未经本轮逐条验证。 |
| [JobSpy](https://github.com/speedyapply/JobSpy/tree/655af2bcb383506506ecbfc0be95a4887245b25e) | MIT / 2026-09-30 | LinkedIn、Indeed、Glassdoor、Google 等聚合抓取，统一 DataFrame | 搜索参数与平台过滤，没有个人证据协议 | 导出 CSV/Excel；没有本任务要求的申请状态机 | **参考数据字段**；可作未来补充适配器。平台描述可能缺失，LinkedIn 正文另需请求；其代理绕封锁建议不引入本项目。聚合结果仍须回到官方入口核验。 |
| [JobHunter](https://github.com/Bynlk/JobHunter/tree/4b5a69010a98b3d80b408fd983c1c2dfa60788e4) | MIT / 2026-05-07 | 实习僧、NCSS、公司官网与企业 API | 关键词、位置、学历等字段筛选 | SQLite 以 URL 去重、导出；没有申请批准链 | **适配 NCSS 端点知识**。实际读取 `crawler/ncss_crawler.py`、`api_crawler.py`、`models.py`；本地重新实现 HTTP 适配器。上游 NCSS 仍通过浏览器 fetch，非实习默认归为校招且正文有截断，不能照抄。README 自认通用公司页抓取成功有限。 |
| [JobCopilot](https://github.com/huluobo2237-pixel/JobCopilot/tree/ca3e729fa12a9ee142a298a01c9cce03244d12f0) | MIT 文件；README 另有非商业表述 / 2026-06-18 | BOSS 搜索页，浏览器扩展 | DeepSeek 简历筛选与逐岗招呼语 | 人工勾选后逐个发简历图片和消息；侧栏日志、已投去重 | **仅参考人工审阅交互**。没有逐条事实证据约束；依赖 DOM、登录态、外部模型；许可证文件与说明口径有差异，不在本轮吸收源码或安装扩展。 |
| [czc-good-job](https://github.com/czc6666/czc-good-job/tree/e07bf4cb663d9531864ca22eb6195b77e064c3b5) | MIT / 2026-04-27 | BOSS 用户脚本与本地 FastAPI | 标题弱信号、JD 正文规则打分；默认方向接近 AI 应用 | 达阈值打招呼，新消息触发发指定简历；默认不续聊 | **参考职业词与正文优先原则**。阈值不等于证据满足，收到消息也不等于对方请求了材料；其直接发送行为不采用。 |
| [boss-auto-apply](https://github.com/Aanlik/boss-auto-apply/tree/7fc55669a14378c941563a883ab06fae9fe8cd01) | 未找到仓库 LICENSE / 2026-08-08 | BOSS 抓取、批次、人工导入 | JD 分析、公司尽调、模型排序、定制文案 | Electron/React/FastAPI；JSON/SQLite；选岗、发送历史、HR 回复与 CRM | **只参考流程和已选岗位范围**。许可未知，不复制实现。其模型、企业查询、浏览器登录和桌面打包依赖显著超过 v0.1；不能将上游自报“发送成功”直接当本项目的现实回执。 |
| [job-agent](https://github.com/Malik1942/job-agent/tree/b859ab6aadb7ecbc61d79bbd54dc1c33f060e25f) | 未找到仓库 LICENSE / 2026-07-31 | Greenhouse、Lever、Ashby 等公开 ATS；可选 Adzuna | 配置事实、answers 文件、规则打分、材料验证；未知必填字段 hold | SQLite tracker、CSV；review/fill/confirm 两阶段、默认 live_submit 关闭 | **只参考批准绑定、未知 hold 和实际发送分离**。许可未知，不复制。ATS、邮箱、Slack 与浏览器机制不整套搬入；上游对各站点风控的判断也未经本轮复验。 |
| [JobScanner](https://github.com/jainary4/JobScanner/tree/315bf3becae155970a2e2f89a11171ce044a80de) | 未找到仓库 LICENSE / 2026-06-19 | Greenhouse / Lever / Ashby，按公司交错发现 | Agno 多 Agent；评分、简历改写、独立事实审计、LaTeX、求职信 | 只生成材料，不发送；按岗位目录留输出 | **只参考独立 claim audit**。不复制源码，不采用“反复改写到分数过线”的成功定义；分数不能证明适配，事实审计也不能靠模型自评替代来源映射。 |
| [Resume Matcher](https://github.com/srbhr/Resume-Matcher/tree/9c05e423dfde44a5b4bb398d2dc7507194252ded) | Apache-2.0 / 2026-09-29 | 用户输入 Master Resume 与 JD；不负责完整岗位发现 | 多模型支持、关键词高亮、简历定制、面试准备、PDF | TinyDB；保存岗位版材料，没有本任务全渠道 CRM 合同 | **参考 diff/对比的用户阅读方式**。现有 context-resume 继续维护事实；不再部署另一套简历权威。云端模型会扩大简历数据披露范围，v0.1 使用本地事实选择。 |
| [原 AIHawk 地址的当前目标](https://github.com/feder-cr/invisible_playwright_mcp/tree/94c9736610b6ca54ed115e6241d8637f4d25a4c3) | 当前 MIT；README 注明 2026-09-02 前版本另按 AGPL-3.0 / 2026-09-25 | **原地址现重定向 `feder-cr/invisible_playwright_mcp`** | 当前产品是隐蔽浏览器 MCP/UI，不是可复用的求职匹配系统 | 浏览器配置、会话、模型服务；本轮未找到当前任务所需 CRM 产品面 | **不采用**。不能按历史 AIHawk 名称、星数或旧文章认领现有功能。本任务不建设浏览器反检测；没有补造历史 AIHawk 快照或许可。 |

## 落到本项目的机制

1. **发现与核验分离**：来源页记录“哪里看到”，官方详情记录“现在能核实什么”。NCSS 的官方平台身份不自动等于雇主直接确认；HTTP 200 也不证明岗位仍开放。
2. **一个岗位、多条来源证据**：保留平台标识和 URL；只有官方地址、稳定岗位身份或显式核实的别名能合并，不能仅因岗位同名就合并。
3. **事实选择与审计分离**：从 `context-resume` 已审事实中选内容，输出基线 diff 与事实 ID；命中技术词不能升级熟练程度、年限、商业效果或独立贡献。
4. **审阅、批准、实际投递分别记录**：每次批准指向确定材料；JD、候选人事实或材料变化后须重新审阅。真实发送确认才记 `applied`，没有发送回执的测试只在测试数据库中演示。
5. **保留反馈历史**：拒绝不能抹掉之前的回复和面试；复盘分别看来源、材料版本、触达与招聘反馈，样本不足不推导策略结论。

本轮对生产源的直接核验入口为 [Greenhouse Job Board API 官方文档](https://docs.greenhouse.io/job-board.html)、[Anthropic 官方招聘页](https://www.anthropic.com/careers) 与 [国家大学生就业服务平台](https://www.ncss.cn/student/jobs/index.html)。真实采集与状态判定的验收以本项目样本回执和运行结果为准，不能由本调研表替代。

## 浏览器适配边界

当前没有 BOSS 在线简历或浏览器自动投递适配器。公开抓取与插件方案不能证明账号下的真实保存或发送；不把页面回退、连接失败或模型自述当作已成功操作。需要使用相关平台时，仍由本人在官方页面处理。
