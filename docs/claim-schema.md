# 事实主张 Schema

[English](en/claim-schema.md) | **简体中文**

事实主张（claim）是记忆的原子单元（atomic unit）：一条事实、一个归属时刻、一个文件。

## raw 记录

文件位于 `raw/` 下，命名为 `YYYY-MM-DD_<topic>_<8-hex>.md`。frontmatter（每个值占一行；所有字段均经校验——超长或多行的值会被**直接拒绝，绝不截断**）：

必填字段（全部必填，逐一精确校验）：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `schema_version` | `2` | 记录 schema |
| `id` | `mem-<uuid>` | 稳定标识 |
| `created` | date | 事实的日期（人为确定，不是文件 mtime） |
| `source` | enum | 由谁写入（`user`、`claude-code`、`codex`、`zcode` 等） |
| `topic` | slug | 分组键（例如 `agent-core-learning`） |
| `kind` | `profile` \| `preference` \| `memory` | 事实类别 |
| `scope` | `global` \| `non-project` \| `project` | 路由作用域 |
| `activation` | enum | 何时可进入上下文（例如 `on-demand`、`bootstrap`） |
| `record_type` | `source` \| `synthesis` | raw 笔记或提炼视图 |
| `summary` | ≤ 300 字符，单行 | 事实主张本身，用一句话表述 |
| `compile_status` | enum | 审阅状态（例如 `done`） |

可选关系字段（默认为空）：`project_id`（scope 为 `project` 时必填）、`supersedes`（本事实取代那些记录）、`derived_from`（证据链；仅 synthesis 可设置）、`covers`（仅 synthesis 可设置）、`conflicts_with`、`resolved_by`、`review_note`、`reviewed_at`。编译器还会在索引上额外维护计算字段（`effective`、`exclusion_reason`、`superseded_by`）——这些你从不手写。

正文是自由格式的 markdown——背景、引文、注意事项。被渲染进视图的是 summary；正文则留在 `raw/` 中作为证据。

## 五种关系

```
supersedes   A ──▶ B     A 取代 B（B 变为已失效）
covers       A ──▶ B     A 是覆盖 raw 记录 B 的提炼记录（两者都可保持有效）
derived_from A ──▶ B     A 的证据包含 B（仅作溯源）
conflicts    A ◀─▶ B     A 与 B 不一致；必须裁决其一
resolves     A ──▶ C     纠正 A 裁决冲突 C
```

编译器只解释这些**显式**关系——绝不依据时间戳，绝不依据热度，也绝不无声地偏向。参见 [06 — 事实主张关系](assets/06-claim-relations.svg) 和 [04 — 事实主张生命周期](assets/04-claim-lifecycle.svg)。

## 有效性

一条记录默认**有效**，除非编译器计算出相反结果——典型情况是它被取代（`superseded_by` 由 supersedes 关系计算得出），或它是一条被提炼记录（synthesis）覆盖的源记录（source）（`exclusion_reason` 是编译器输出，不是手工设置的字段）。`compile` 每次运行都会重新计算。

`compile` 为每条记录重新计算有效性，然后渲染视图。有效记录的条数，就是各 agent 实际路由时真正用到的数量——见 `compiled/memory-index.yaml: records.*.effective`。

## 纠正

纠正（correction）是一条普通的事实主张，并在冲突记录上设置 `resolved_by`。纠正从不具破坏性：旧文本带着标记留在 `raw/` 中；纠正渲染进 `compiled/corrections.md`，直到双方都老化出局。“已更新”不等于“已正确”——纠正是一条显式胜出的新事实。

## 字段限制及其原因

- 所有被渲染的字段一律**300 字符、单行、无控制字符**：注入防御（injection defense）与 diff 卫生（保持可 diff 性）——无法在一行内 grep 到的事实主张是一条笔记，而不是事实主张。
- 文件名携带日期和主题，因此无需打开文件，排序就有意义；末尾的十六进制串让重名冲突不可能发生。
