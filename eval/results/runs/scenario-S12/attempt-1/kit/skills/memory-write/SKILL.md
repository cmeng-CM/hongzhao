---
name: memory-write
description: 将用户明确要求长期保留的事实、偏好、决策、经验或非项目重要事项写入 hongzhao raw 候选；也用于用户明确要求纠正、停止使用或删除某条长期记忆时检查影响。只维护 raw，不编译、不修改项目文件或客户端准则。
---

# memory-write

## 边界

- 仅在用户明确说"记一下""写入记忆""长期保存""纠正这条记忆""忘记/删除这条记忆"等请求时运行。
- 普通项目进度、任务清单、当前会话过程不写 raw；项目当前状态使用 `memory-project-context`；交接类内容由客户端自身机制处理。
- 非项目内容只有用户明确认为值得长期保留时才写入。
- 本 Skill 只维护 raw；不修改 compiled、render、项目文件或客户端规则文件（托管块由引擎维护）。
- 字段约束速查：进入渲染的字段必须单行、不超过 300 字符、不含控制字符；`id` 与关系列表必须是 `mem-<UUID>` 形态。

## 命令与根目录

- 命令统一为 `hongzhao <子命令>`；在记忆根目录执行，或用 `--root <路径>` 显式指定。
- 记忆根的判定与诊断：`hongzhao root`。

## 新增候选

1. 读取 `raw/` 中相关 topic 和 `compiled/memory-index.yaml`；不要扫描无关项目目录。
2. 判断 scope：
   - `global`：稳定用户背景、长期偏好、通用工作方式或全局事项；
   - `project`：项目长期决策、经验和约束，必须绑定已登记 `project_id`；
   - `non-project`：学习、工具、个人决策及其他非项目长期事项。
3. 确定 `activation`：只有适合所有新会话默认看到的摘要才使用 `bootstrap`，其余使用 `on-demand`。
4. 分类、scope、项目归属或默认激活会造成明显不同结果时，给出推荐并只问一个问题；低歧义字段直接填写。
5. 创建 `record_type: source`、`compile_status: new` 的 raw，不写 `derived_from` 或 `covers`。
6. 文件名为 `raw/YYYY-MM-DD_<topic>_<UUID前8位>.md`，不得覆盖已有文件。
7. 运行 `hongzhao validate`。`review-needed` 表示候选已合法写入，不代表已经进入 Effective Memory。

## Raw schema

```yaml
schema_version: 2
id: mem-<UUID>
created: YYYY-MM-DD
source: claude-code | codex | zcode | user | migration | other
topic: stable-topic-key
kind: profile | preference | memory
scope: global | project | non-project
project_id: proj-<UUID> # 仅 project 必填
activation: bootstrap | on-demand
record_type: source
summary: 一句当前事实主张摘要
compile_status: new
supersedes: [] # 用户明确纠正已有事实时可选
```

正文只写已确认的事实、决策或经验，不复制对话过程。`created` 只用于追溯，不填写过期时间。

## 生命周期

- `new` 阶段允许修正正文、summary、分类和关系；`id`、`created`、`source` 不改。
- `done` 后正文和事实性 metadata 冻结；错误通过新 source/synthesis + `supersedes` 修正。
- `activation` 是路由 metadata，可以单独调整。
- 不使用 `kind: correction`；纠正仍使用原 kind，并通过 `supersedes` 表达。

## 明确删除

用户明确要求删除且目标唯一时：

1. 在 `memory-index.yaml` 检查 `derived_from`、`covers`、`supersedes` 和冲突引用。
2. 没有引用时可以删除 raw；有引用时必须展示影响并确认，不静默制造断链。
3. 删除后明确说明派生视图需要运行 `memory-compile` 重建。
4. 不声称已清除 Git 历史。

## 输出

只报告新增、修正或删除的 raw、摘要、scope、activation 和当前 `compile_status`。不要声称 Bootstrap 已刷新。
