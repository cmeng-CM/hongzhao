---
name: memory-compile
description: 在用户明确要求编译、归并或刷新长期记忆时，审阅 hongzhao raw 候选，执行语义提炼、显式覆盖、纠正和冲突确认，再用确定性引擎全量重建 Effective Memory、索引、状态视图与 Bootstrap，并刷新 inline 客户端快照和运行 doctor。
---

# memory-compile

## 职责

```text
本 Skill          语义审阅、必要询问、写 synthesis 和关系
hongzhao 引擎     schema、关系图、全量渲染、桥接和健康检查
```

- 只在用户明确要求"编译记忆""归并记忆""刷新记忆上下文"时运行。
- 不创建或更新项目 `project-view.md`，不修改项目正文，不处理交接类内容。
- 不直接编辑 compiled 或 render；所有派生文件由引擎重建。
- 字段与关系速查以内嵌下文为准；命令统一 `hongzhao <子命令>`，在记忆根目录执行或 `--root` 显式指定。

## 流程

1. 运行 `hongzhao validate`，读取全部非模板 raw 和 `compiled/memory-index.yaml`。
2. 审阅每条 `compile_status: new`：
   - 修正候选阶段的 summary、正文、scope、topic、kind 和 activation；
   - 与现有事实主张（claim）独立且无歧义时，标记 `done`；
   - 同 scope、同 project_id 的重复或互补记录可生成 synthesis；
   - scope、project_id、activation 不一致或长期含义差异明显时，给出推荐并询问；
   - 新候选与 done 冲突时，旧 done 保持有效，新候选继续 pending，提示用户裁决。
3. 处理 synthesis：
   - 使用 `record_type: synthesis`；
   - `derived_from` 只列直接来源；
   - 只有完整承担来源的仍有效内容时才填写 `covers`；
   - 跨 scope 或跨项目提炼必须用户确认，只能用 `derived_from`，不得用 `covers`；
   - 普通归并不用 `supersedes`，事实失效才使用。
4. 处理冲突：
   - Agent 只能提出冲突候选，用户确认前不写 `conflicts_with`；
   - done-done 冲突必须展示两条记录、来源和具体冲突点并询问；
   - 用户确认冲突但暂不裁决时写 `conflicts_with`，两条事实主张局部退出并使 health=degraded；
   - 裁决结果通过 resolution synthesis 和 `resolved_by` 闭合；旧结论失效时同时使用 `supersedes`；
   - 新候选被否决时标记 `rejected`，填写 `reviewed_at` 和简短 `review_note`。
5. 再次运行 `hongzhao validate`，确保 raw 和关系图合法。
6. 依次运行：

   ```bash
   hongzhao compile
   hongzhao bridge-install all
   hongzhao doctor
   ```

7. 读取 `compiled/last-compile-diff.md` 作为汇报依据（对账步骤）：
   - 向用户报告实际 delta：新增生效、退出生效、新候选、新拒绝各若干条，以及计数表和健康迁移；
   - 与第 2–4 步的审阅意图对账：审阅了 N 条、diff 与之不符（多生效、漏生效、意外退出）时，回到 raw 修正后重新编译，不得带偏差宣称完成；
   - 首次编译无基线（diff 只有计数表）时如实说明，不虚构逐条 delta。

Claude Code 通过 `@` 实时读取 Bootstrap；Codex、ZCode 等 inline 客户端使用嵌入快照，因此编译后必须刷新启用客户端的托管块。

## 当前采纳规则（Canonical）

- 不按时间、topic 或"最新记录"自动择一。
- `derived_from` 只表示来源，不隐藏记录。
- `covers` 才产生 `covered-by-synthesis`。
- `supersedes` 才表示事实失效。
- `new`、`rejected`、superseded、covered 和未解决冲突不进入 Effective Memory。
- 引擎不摘要或重写正文，直接渲染当前采纳记录的 summary 和正文。

## 产物与健康

每次全量生成：

- `compiled/effective-memory/index.md`
- `compiled/effective-memory/global.md`
- `compiled/effective-memory/non-project.md`
- `compiled/effective-memory/projects/<project_key>.md`
- `compiled/memory-index.yaml`
- `compiled/current-state.md`
- `compiled/corrections.md`
- `compiled/last-compile-diff.md`
- `render/bootstrap.md`

健康状态：`ok`、`review-needed`、`degraded`。pending 不阻断现有有效视图；schema/契约/关系错误和已确认的 done-done 冲突才 degraded。
