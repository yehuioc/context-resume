---
module: career
---

# 求职执行系统

`career-ops` 将公开岗位、已审核的候选人事实、岗位版材料和求职反馈接入同一条状态链。它帮助判断为什么值得投、还有哪些未知、该展示哪些已有证据；材料审阅、人工批准和实际发送分别记录。当前没有自动发送、海投、账号 Cookie 或 HR 消息监听。

本目录是 `context-resume` 的求职流程模块，使用项目根目录的一份 Git。统一导航、公开与个人资料边界见 [项目入口](../README.md)；操作命令可以从本模块目录运行。

## 安装与开始

需要 Python 3.10+。岗位采集、匹配和状态存储使用标准库；PDF 生成使用 ReportLab，PDF 文本检查使用 pypdf。PyMuPDF 可选，用于图片预览，也可替代 pypdf 做文本检查。

在项目目录运行：

```powershell
python -m pip install -r requirements.txt
python -m career_ops --help
python -m career_ops status
```

Windows 也可以使用 `scripts/career-ops.cmd`；它调用当前环境的 `python`。测试环境使用 `python -m pip install -r requirements-dev.txt`，再运行 `python -m pytest -q`。测试临时目录和缓存都在本项目的 `private/test-tmp/`。

## 候选人事实与个人资料

默认读取同一项目的 `../self/career-profile.json`；公开下载不包含本人事实。`examples/career-profile.json`、`examples/evidence.md` 和 `examples/baseline.md` 是合成示例，不是任何人的真实履历。可以先检查示例：

```powershell
python -m career_ops --candidate examples/career-profile.json --db private/demo.sqlite3 status
```

真正生成材料前，要配置自己的 `career-profile-v1` 文件，填写本人真实事实、已审原句与必要条件。每条事实必须有证据文件、定位和 SHA-256；基线也必须绑定原始简历与哈希。校验见 `career_ops/candidate.py`。证据变化后须重新审核，不能直接更新哈希掩盖内容变化。

事实库在同一项目的 `self/` 中维护。在忽略的 `private/local-config.json` 中配置外部证据工作区 `workspace_root` 和 `candidate_profile`；相对路径以本模块目录为基准。明确授权的证据范围必须覆盖事实文件及证据文件，例如：

```json
{
  "workspace_root": "..",
  "candidate_profile": "../self/career-profile.json"
}
```

`CAREER_WORKSPACE_ROOT` 和 `CAREER_OPS_CANDIDATE` 可分别覆盖这两个配置。命令的 `--candidate` 可选择具体事实文件，`status` 会显示实际采用的事实入口。事实源由本人维护，本项目只读，不按 JD 新增经历或升级熟练度。

真实 JD、原响应、SQLite、投递包、简历预览、联系人、回复与验收材料全部保存在忽略的 `private/`。这些资料需要单独备份，GitHub 源码不能恢复个人台账。网页 Project Brain MCP 可分别通过源码来源和已授权的 `private/` 目录来源读取；源码公开不改变私人资料的读取授权。

## 从岗位到审阅材料

国内来源是 NCSS，海外来源是雇主 Greenhouse 公共 Job Board API。来源刊登、雇主独立核验、明确关闭、超时和未知分别保存。`official_platform_live` 只表示官方平台页面可核实，不等于雇主已确认仍在招；`employer_verified` 需要雇主官网与该岗位申请入口的对应证据。

```powershell
python -m career_ops discover ncss --keyword "AI 实习" --limit 20
python -m career_ops discover greenhouse --board anthropic --limit 3
python -m career_ops list
python -m career_ops verify 1
python -m career_ops assess 1
python -m career_ops prepare 1
python -m career_ops report
```

机会 ID 使用实际返回值，示例 `1` 不代表推荐岗位。采集保存原响应与回执；手工导入默认未核验。带回执导入时使用 `import --file private/samples.json --receipt private/collection-receipt.json`，核对原响应、摘要和岗位身份后才保留采集核验。`scripts/collect_samples.py` 可采集批量验收样本，所有结果仍留在 `private/`，不会投递。

匹配输出要求原句与位置、直接或部分证据、明确缺口、未知和需要核验的问题。评分只用于排序，不能覆盖来源失败、届别冲突或未知条件。当前匹配采用可检查的本地规则，不能穷尽任意 JD 语义。

投递包包含原 JD、要求到证据的映射、理由与风险、原始简历、逐行差异、MD/HTML/PDF 简历、逐句主张审计、联系草稿和项目证据。内容仅从已审核的事实原句或批准变体中选择与排序。`private/review/index.html` 是本地只读审阅入口。

## 批准、实际投递与反馈

```powershell
python -m career_ops shortlist 1 --actor 用户 --note "实际选择理由"
python -m career_ops approve 1 --digest 实际材料摘要 --actor 用户 --confirm-reviewed
python -m career_ops mark-applied 1 --confirmation user_confirmation --evidence "真实发送确认或回执" --confirm-sent
python -m career_ops record-reply 1 --type hr_reply --content "实际回复" --event-id "渠道消息唯一编号"
python -m career_ops funnel
python -m career_ops next-actions
python -m career_ops export
```

岗位 ID、材料包 ID 与材料摘要以本次输出为准。短名单、材料批准和实际发送是三个动作；参数不能代替用户授权或证明发送。批准绑定当前 JD、候选人版本和材料摘要，任何变化或撤销都会使旧批准失效。接受未知条件须显式使用 `--accept-unknowns --review-note`，仍保留 Unknown；明确硬冲突、关闭、来源失败或缺少可信入口不能由风险接受绕过。

投前联系单独记录，不进入投后回复率。后续拒绝不会抹掉已有回复或面试。相同回复默认去重；另一次真实发生的相同回复需提供独立事件 ID 或实际时间。`private/exports/career-ops-readonly.json` 可供其他工作台只读消费，机会、投递和互动仍只有本项目一个写入权威。

## 状态模型与研究

`opportunities` / `source_aliases` 保存机会与来源身份；`observations` / `jd_revisions` 保留原观察和实质变化；`assessments` / `packets` 绑定事实与材料版本；`human_decisions` / `approvals` / `applications` 区分选择、批准和实际投递；`contacts` / `interactions` / `next_actions` 接续反馈。`events` / `legacy_records` 保存追加事件和旧记录，迁移不会凭旧评分补造批准或投递。

开源取舍与固定提交依据见 [开源研究](docs/oss-research.md)。`scripts/research_oss.py` 只读取上游说明与许可证，不执行上游代码。默认登记使用 `examples/oss-registry.json`，下载快照保存在 `private/oss-reference/`；本机可以通过 `private/local-config.json` 的 `oss_registry`、`oss_reference` 或脚本的明确参数接续既有资料。

原系统完成过本地岗位、材料和状态链路验收；个人验收原件保留在 `private/acceptance/`。合成测试不证明真实投递或 HR 回复，也不证明公开接口永久可用。本项目没有 BOSS 在线简历自动更新或浏览器自动投递适配器。

当前仅公开源码，尚未新增开源许可证；第三方依赖遵守各自许可。
