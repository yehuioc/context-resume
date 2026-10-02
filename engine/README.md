# 脱敏项目证据包引擎

位置：`E:\agentv2\workbench\projects\context-resume\engine`。使用项目根 Git。

从结构化项目事实和操作者独立维护的来源清单生成证据台账、贡献边界、简历表达、岗位匹配及面试追问。输入不足、来源不存在、事实冲突、个人敏感信息或越界请求会拒绝生成；模型输出不自动成为证据。

```powershell
pwsh -NoProfile -File engine/scripts/build-customer-pack.ps1 -InputJson engine/product/sample-output.json -SourceManifestJson engine/product/sample-source-manifest.json -OutputDir private/evidence-pack -HumanReviewConfirmed
pwsh -NoProfile -File engine/tests/test-build-customer-pack.ps1
```

命令从项目根执行，生成 Markdown 与 HTML。提示词在 `methods/生成提示词.md`；相对样例位置为 `product/`。`customer_id` 与原脚本名为已有协议兼容字段，只表示材料编号；引擎不包含收费、订单或闲鱼运营。

本人逐岗简历需要实名联系方式，使用 `career` 的事实账本与 PDF 投递包生成器；不能用脱敏引擎的隐私拒绝逻辑强行处理实名投递，也不能直接把脱敏案例升级为本人经历。完整流程见 [统一入口](../README.md)。
