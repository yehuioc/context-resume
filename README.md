---
git_mode: independent
---

# 简历与求职工作台

唯一项目目录：`E:\agentv2\workbench\projects\context-resume`。
GitHub：[yehuioc/context-resume](https://github.com/yehuioc/context-resume)。

把本人已经审核的简历事实接到岗位发现、JD 证据匹配、针对性材料、人工审阅、真实投递记录和反馈。私人资料与公开实现共用这个项目；Git 只发布源码、说明和合成样例。

## 模块与权威

| 文件夹 | 用途与入口 |
|---|---|
| `self/` | 私人简历基线、事实账本、原始对话、证据和面试材料；默认事实入口 `self/career-profile.json`。已有 v4.2 在 `self/baselines/`，不是重新编造一份经历 |
| `career/` | 岗位采集、核验、Requirement → Evidence → Unknown → Verify、投递包、人工批准、发送确认和反馈；唯一求职状态为 `career/private/career-ops.sqlite3`，详见 [操作说明](career/README.md) |
| `engine/` | 来源清单独立校验的脱敏项目证据包生成；输出 Markdown/HTML，详见 [引擎说明](engine/README.md) |
| `core/` | 共享结构、表达方法、排版资产和来源研究；关键词覆盖只作辅助，不能代替事实或岗位判断，详见 [共享资产说明](core/README.md) |
| `knowledge/` | 简历资料知识库的研究与边界；目前没有完成的编译器或检索引擎，详见 [当前状态](knowledge/README.md) |
| `legacy/` | 旧求职数据库的只读来源档案；没有运行入口，详见 [档案说明](legacy/README.md) |

本人事实账本 `career-profile-v1` 与通用脱敏证据包 `evidence-pack` 是不同实体，不强行合并字段。`career` 只从已经审核且哈希一致的事实中选择表达，生成的匹配和材料不会自动升级为新事实；反馈进入同一岗位库，事实变更需复核。

## 从项目根运行

Python 3.10+；证据包引擎另需 PowerShell 7。PDF 使用 ReportLab，PDF 检查使用 pypdf。

```powershell
python -m pip install -r requirements-dev.txt
python -m career_ops status
python -m career_ops list
python -m career_ops discover ncss --keyword AI --limit 10
python -m career_ops assess 1
python -m career_ops prepare 1
python -m career_ops review 1
python -m career_ops report
python -m career_ops next-actions
python -m career_ops funnel
```

`1` 是实际导入后返回的岗位 ID。材料审阅后再按 `career/README.md` 中的 `approve` 和 `mark-applied` 登记；系统没有自动发送命令。未知项保留，批准与发送是独立事件。公开下载没有本人资料，先使用 `--candidate career/examples/career-profile.json` 运行合成示例；它不会证明真实投递或 HR 回复。

```powershell
python -m career_ops --candidate career/examples/career-profile.json status
pwsh -NoProfile -File engine/scripts/build-customer-pack.ps1 -InputJson engine/product/sample-output.json -SourceManifestJson engine/product/sample-source-manifest.json -OutputDir private/example-evidence -HumanReviewConfirmed
python -m pytest -q
pwsh -NoProfile -File engine/tests/test-build-customer-pack.ps1
```

本机外部证据根和资料位置可在 `career/private/local-config.json` 配置；环境变量 `CAREER_WORKSPACE_ROOT`、`CAREER_OPS_CANDIDATE`、`CAREER_OPS_DB` 可覆盖相应默认值。来源样例与基线的字节哈希由 `.gitattributes` 保持一致。

投递包、文件摘要和采集回执中的文件引用以 `career/` 为基准，保存为 `private/...` 相对路径；读取时由同一模块解析，不依赖命令启动目录。审阅页使用相对链接。候选人证据按事实账本所声明的证据根解析，外部证据根仍需本机配置。

## 网页读取与公开边界

网页 Project Brain MCP 使用唯一来源名 `context-resume`，directory 模式读取本项目的源码，以及已经授权的 `self/`、岗位库和投递包；简历 PDF/DOCX 可通过二进制读取取得。先列目录，再按任务读取，完整快照需要分页。工具只读，网页不会执行投递或修改事实。

GitHub 不上传 `self/`、`requirements/` 中的私人对话、任何 `private/`、数据库、个人投递包或凭证。MCP 同样排除凭证、依赖、测试缓存、私有 Git 历史备份及闲鱼运营档案。MCP 是授权读取渠道，不等于公开发布。

闲鱼的定价、订单、上架、客服、营销和商业验收不属于本项目的运行模块。历史资料保存在本地 `private/archives/pre-integration/`，没有删除个人简历或原始证据。`xianyu-ops` 与注意力恢复项目 `focus-resume-console` 继续独立运行。

本项目只有根目录一份活动 Git，MCP 也只登记这一真实目录。日常任务从本 README 进入 `self/` 的事实和 `career/` 的流程；其他模块按上表读取。历史源码、原始记录与 Git bundle 位于本地 `private/archives/`，仅用于追溯，不是运行入口。

第三方方法与资产保留各自来源、提交和许可标注。当前仅公开源码，未另行声明整仓开源许可。
