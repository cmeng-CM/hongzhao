---
name: memory-project-context
description: 为明确项目创建、更新或刷新可见的 project-view.md，维护项目契约与资料入口，并同步 hongzhao 项目注册表；不写长期 raw，不处理交接类内容。
---

# memory-project-context

## 边界

`project-view.md` 是项目唯一的项目契约和可见综合视图：frontmatter 供 hongzhao 引擎确定性读取，正文供人审阅和按需读取。

- 仅在用户明确要求创建、更新、同步项目上下文或刷新项目视图时运行。
- 输入必须唯一确定项目根目录；不能确定时给出推荐并询问。
- **新建契约前先查已有契约**：查记忆根 `registry/project-registry.yaml`、记忆根 `projects/<key>/` 下的 central 契约、以及项目根自身的 `project-view.md`；已有契约（无论在哪一处）就地维护，**绝不新建第二份**。
- 不创建 `.agent-context.md`，不向客户端规则文件写项目指针。
- 不写 raw，不编译 Effective Memory；交接类内容由客户端自身机制处理。
- 不根据文件修改时间或 Git 状态推断 `current_state`、`next_action` 或项目状态。
- `current_state` 和 `next_action` 是契约摘要快照，不是进度日志；详细进展在项目资料中。
- 不从项目资料全文自动猜测关键决策、问题、卡点或风险；这些内容由视图人工区维护。
- 命令统一 `hongzhao <子命令>`，在记忆根目录执行或 `--root` 显式指定。

## 文件结构

```text
项目根目录/
├── project-view.md       # 项目契约与综合视图（项目根形态）
└── 项目详细资料...
```

central 形态（无项目根契约的项目）由 `hongzhao project-register <项目根路径>` 创建于记忆根 `projects/<project_key>/`。视图正文必须包含且只允许一个自动区块：

```markdown
<!-- PROJECT_VIEW_GENERATED:START -->
...
<!-- PROJECT_VIEW_GENERATED:END -->
```

自动区包括项目概况、资料入口和 project memory 链接；标记外是人工区，至少保留"关键决策"和"问题、卡点与风险"两个标题。

## Schema

```yaml
schema_version: 2
project_id: proj-<UUID>
project_key: stable-human-readable-key
project_name: 项目名称
updated_at: YYYY-MM-DD
status: active | blocked | paused | completed
purpose: 项目稳定定位的一句话
current_state: 当前阶段或状态的一两句话
next_action: 当前唯一优先方向
activation: bootstrap | on-demand
entrypoints:
  - 相对项目根目录的路径
```

`project_id` 是项目管理性唯一标识，不能因项目改名或文件重命名而改变。`project_key` 是稳定的人类可读键，只允许小写字母、数字和连字符，用于 project memory 文件名与链接 target；不能自动从项目名称反复推导。`entrypoints` 只保存相对路径字符串，入口说明写入正文自动区的"核心资料入口"。frontmatter 只允许以上契约字段。

## 归档目录排除

- 项目根目录下任意层级、名称不区分大小写且完整等于 `Archive` 或 `99-Archive` 的目录默认排除。
- 创建或刷新项目视图时，不扫描这些目录，不从中提取项目概况、状态、决策或资料入口，也不将其中路径写入 `entrypoints`。
- 现有 `entrypoints` 指向归档目录时，刷新时自动移除并在结果中报告；不删除、不移动、不修改归档文件。
- 只有用户明确指定归档内容，或明确要求历史追溯时，才为当前任务临时读取。
- 正文自动区必须包含"读取边界"，显示上述默认排除规则。

## 创建

1. 读取记忆根 `registry/project-registry.yaml` 与记忆根 `projects/`，确认项目是否已有契约或登记（见边界第三条）。
2. 没有旧契约时，只有在用户确认 `purpose`、`current_state`、`next_action` 和 `status` 后创建；不写占位文字。
3. 创建时要求用户确认稳定的 `project_key`；检查它未被其他登记项目使用。
4. `entrypoints` 只列项目详细资料，不需要把 `project-view.md` 自身列为入口。
5. 枚举项目根概况和候选入口时先排除归档目录。
6. 新项目或注册表缺少该项目时，在用户确认后于记忆根运行 `hongzhao project-register <项目根路径>`；已有且路径一致的登记不重复创建。

## 更新与刷新

1. 读取已有 `project-view.md` 的 frontmatter、entrypoints 和当前会话已确认事实。
2. 移除指向归档目录的既有 `entrypoints` 并记录到完成报告；不得打开归档文件做内容判断。
3. 状态、定位、当前阶段或下一优先方向发生变化时，生成最小 frontmatter diff；更新 `updated_at`。没有用户确认的事实不写入。
4. 只替换 `PROJECT_VIEW_GENERATED:START/END` 之间的内容，保留人工区原文；自动区固定包含"读取边界"。
5. 已有正文但缺少自动区块标记时，不覆盖，先请求确认迁移边界。
6. project memory 只生成链接，不复制 raw 或 Effective Memory 正文；链接 target 使用对应契约的 `project_key`，链接不存在时明确标记待生成。

## 人工维护区

- **关键决策**：记录当前仍有效的决策摘要，完整论证留在项目资料。
- **问题、卡点与风险**：记录当前未解决事项、影响和处理线索；解决后由人工关闭或移除。
- 人工区不会自动写入 project raw；需要长期保留时另行调用 `memory-write`。

## 完成后检查

在记忆根目录执行：

```bash
hongzhao project-check <project-root>
hongzhao render
hongzhao bridge-install all
hongzhao doctor
```

同时确认：

- `project-view.md` frontmatter 可解析且 `project_id` 与注册表一致；
- `entrypoints` 不包含归档目录，自动区包含"读取边界"；
- 自动区标记成对出现，人工区没有被覆盖；
- 生成的项目资料和 project memory 链接可解析。
