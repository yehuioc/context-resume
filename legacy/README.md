# 旧求职系统兼容入口

位置：`E:\agentv2\workbench\projects\context-resume\legacy`。使用项目根 Git。

原 `internship-job-agent` 的数据库 `var/job-agent.sqlite3` 原字节保留，既有线索、简历快照和事件已作为来源记录进入 `career`；旧记录不会自动制造实际投递或新批准。

`scripts/job-agent.cmd` 与 `scripts/job-agent.ps1` 保留只读兼容调用。`status/doctor/init/verify/list/show/report` 转发统一系统，其中 `show` 使用当前机会 ID。旧添加、修改、批准、发送和自动化命令明确拒绝，原实现与文档留在本地 `private/archives/pre-integration/legacy-source/`。

```powershell
python -m career_ops migrate-legacy
```

迁移只读旧源库；路径兼容入口保持旧来源身份，重复迁移不再创建重复记录。日常操作使用 [统一项目入口](../README.md)，不继续部署旧运行时。
