# 旧求职来源档案

位置：`E:\agentv2\workbench\projects\context-resume\legacy`。使用项目根 Git。

原 `internship-job-agent` 的数据库 `var/job-agent.sqlite3` 原字节保留，既有线索、简历快照和事件已作为来源记录进入 `career`；旧记录不会自动制造实际投递或新批准。

本目录没有命令入口或活动状态库。原实现与文档保存在本地 `private/archives/pre-integration/legacy-source/`，仅用于追溯。日常运行从 [统一项目入口](../README.md) 进入 `career`。

```powershell
python -m career_ops migrate-legacy
```

需要重新导入时，在项目根运行上面的命令；来源身份固定为项目内 `legacy/var/job-agent.sqlite3`，重复导入不创建重复记录。历史记录中的旧路径是当时的原文，不作为当前路径解析或执行。
