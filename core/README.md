# 简历共享资产

路径：`E:\agentv2\workbench\projects\context-resume\core`。本目录使用项目根 Git，不拥有独立 Git 或求职状态库。

`schema/` 保存通用证据包、早期档案和历史追踪格式；当前本人审核账本由 `career/career_ops/candidate.py` 验证 `career-profile-v1`。旧 tracker schema 仅解释历史数据，不是当前写入协议。

`methods/` 保存 JD 表达、贡献边界、故事库和能力缺口的方法；`render/` 保存样式与模板；`research/` 保留研究依据。来源与许可标注继续保留，上游原始快照在本地归档 `private/archives/pre-integration/upstream/`。

`scripts/jd_match.py` 只计算词语覆盖，不能证明满足要求；正式判断使用 `career` 的证据匹配。`scripts/upskill_gap.py` 默认只读当前岗位库统计术语，也支持历史 tracker 或只读导出，不创建另一份状态。

旧 `scripts/tracker.py` 的读命令转到 `career`；添加和修改旧 tracker 已停用。旧 `scripts/render_pack.py` 转到 `engine` 的来源校验生成器，必须提供独立来源清单和人工复核确认，不能绕过证据校验生成正式材料。

运行方式与公开、私人资料边界统一见 [项目入口](../README.md)，具体位置 `E:\agentv2\workbench\projects\context-resume\README.md`。
