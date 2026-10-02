---
producer: claude-code
producer_role: foreground-worker
producer_evidence: "2026-08-01 core 大改吸收;RenderCV 同数据多主题思想 + yamlresume 数据可换渲染器约束"
review_owner: codex-controller
review_state: needs_review
canonical_status: candidate
upstream_source:
  - project: rendercv/rendercv
    commit: 1d4b87b
    license: MIT
    note: "8 主题同数据输出 + JSON Schema 交互"
  - project: yamlresume/yamlresume
    commit: f3ff4c8
    license: MIT
    note: "数据永远属于用户、渲染器可换"
absorbed_by: claude-code
method: render-spec
---

# 渲染规范(数据 → 成品)

## 总原则(吸收自 RenderCV + yamlresume)

1. **一份 schema 数据,多种成品**:同一份 JSON(evidence-pack/candidate-profile)可渲染出不同形态——一页投递简历、完整简历、证据包 Markdown/HTML、PDF;
2. **数据永远属于用户,渲染器可换**:schema 数据是唯一事实结构,渲染层(HTML/CSS/PDF)可替换而不迁移数据;
3. **内容与样式分离**:模板只放结构与样式,内容全部来自 schema 字段(与 lapis-cv 的 Markdown+CSS 主题同哲学)。

## 渲染管线

```text
core/schema/*.json(事实层)
  → 模板填充(core/render/templates/*.md + CSS)
  → 成品:
     ├── Markdown(默认,版本可控)
     ├── HTML(CSS 主题:classic/serif)
     └── PDF(2B 阶段:HTML→PDF 或 typst 管线)
```

## 主题系统(吸收 RenderCV 8 主题与 LapisCV 双版)

- `core/render/css/main.css`:基础排版(字号/行距/边距变量);
- `classic-obsidian.css`:经典中文版(思源字体);
- `serif-obsidian.css`:衬线正式版;
- 品牌色统一 `--color-accent: #2b4c7e`(已从上游 #4870ac 调整);
- 未来新增主题 = 新增一个 CSS 文件,数据不动(RenderCV 模式)。

## JSON Schema 交互(2B 阶段实现)

参照 RenderCV 的 JSON Schema 自动补全:为 3 个 schema 生成编辑器可用的补全与内联文档,减少手工填写错误。

## 与内核的接法

- 当前 service 生成器产出固定证据包 Markdown/HTML——本规范是 2B 阶段扩展方向:同一证据包数据,可另渲染"一页投递版""完整简历"等形态;
- 模板占位符 `{字段}` 与 schema 键名一一对应,填充逻辑由 2B 渲染组件实现;
- 客户交付物形态变化不改变 schema(数据解耦)。
