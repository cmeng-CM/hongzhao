# 升级 hongzhao

[English](en/UPGRADE.md) | **简体中文**

两类读者，一个文件——与 [INSTALL.md](INSTALL.md) 的划分相同。人类：三条命令见[手动升级](#手动升级)。AI 智能体：你的协议是[智能体升级协议](#智能体升级协议)——用户要求你升级 hongzhao 时，照它执行。

## 升级会动什么（以及从不动什么）

`pip install -U hongzhao` 只替换引擎（engine）。其余一切都发生在你运行升级序列时，并遵循以下契约：

| 产物 | 归属 | 升级时 | 契约 |
| --- | --- | --- | --- |
| 引擎（pip 包） | hongzhao | 由 pip 替换 | — |
| 记忆库（kit）的 `skills/`、`templates/` | 随包同步 | 三态同步（`skills-install`）：完全相同→覆盖；你改过→你的版本保留，新版本落地为 `.new`；已从包中移除→保留 | 你的编辑始终在 `.new` 审阅中胜出，绝不静默覆盖 |
| `compiled/`、`render/` | 引擎 | 由 `compile` 完全重新生成 | 派生数据，从不迁移；删除后重新编译即等效 |
| 客户端托管块（managed block） | 引擎（`bridge-install`） | 从新的启动摘要（bootstrap）刷新 | `hongzhao:start/end` 之外的内容保持逐字节一致 |
| `raw/`、`config.yaml`、`registry/`、`projects/` | **你** | **从不写入** | 源数据对引擎只读；格式变更只能通过未来显式的 `migrate` 命令进行，绝不静默发生 |

版本偏差（version skew）的可见性：只要记忆库落后于已安装的包，`doctor` 就会警告 `SKILL_STALE`（记忆库 skills 由旧引擎同步）和 `BOOTSTRAP_STALE`（启动摘要由旧引擎渲染）。运行升级序列后，两者都会消除。

开启 `git.auto_commit` 的记忆库（独立 git 仓库时缺省开启）：升级序列第 3 步 `compile` 会自动产生一条固定格式的 kit 提交（`hongzhao compile v<版本> …`）；任何 git 失败都只降级为 warning，不会阻断升级。

## 让 AI 智能体替你升级（一句话）

告诉你的编程智能体：

```text
阅读 https://github.com/cmeng-CM/hongzhao/blob/main/docs/UPGRADE.md 并帮我升级 hongzhao。我的记忆库位于 ~/hongzhao。
```

## 手动升级

```bash
cd ~/hongzhao && git add -A && git commit -m "pre-upgrade"  # 普通文件：git 就是安全网
pipx upgrade hongzhao        # 或者：python3 -m pip install -U hongzhao
hongzhao --root ~/hongzhao upgrade
# 预期输出：upgrade [1/5] ... upgrade: ok (engine <version>)
```

`hongzhao upgrade` 严格按此执行：`validate → skills-install all → compile → bridge-install all → doctor`，在第一个非零退出的步骤停止。如果你愿意，也可以自己按该顺序运行这五条命令——这条命令除此之外不做任何其他事。

### 故障排查

| 症状 | 处理 |
| --- | --- |
| 在第 2 步停止，报 `SKILL_MODIFIED ... kept yours; candidate written to ...new` | 你定制过记忆库的某个 skill。对比 `SKILL.md` 与 `SKILL.md.new`，手工合并，删除 `.new`，重新运行 `hongzhao upgrade` |
| 在第 1 步（`validate`）停止 | 记忆库存在早于本次升级的源数据问题；先按 validate 输出的信息修复 |
| `pip install -U` 之后 `doctor` 立即警告 `SKILL_STALE` / `BOOTSTRAP_STALE` | 符合预期：记忆库落后于新引擎。运行 `hongzhao upgrade` |
| git diff 显示 `compiled/` 出现大量变化，但 `last-compile-diff.md` 的计数为 0 | 符合预期：引擎发布可能改写骨架文案；你的记录的有效性不受影响 |
| 需要回滚 | `git -C ~/hongzhao checkout .` + `pip install hongzhao==<old>` + `hongzhao --root ~/hongzhao compile`——源数据、引擎与派生数据各自独立回滚 |

## 智能体升级协议

你是被用户要求升级 hongzhao 的 AI 编程智能体。严格按本协议执行。

1. **先检查。** 在改动任何东西之前，报告 `hongzhao --version`、`hongzhao --root <PATH> doctor` 的输出，以及记忆库是否是一个工作树干净的 git 仓库。
2. **先备份。** 如果记忆库是 git 仓库，先提交所有内容（`git add -A && git commit -m "pre-upgrade"`）。如果不是，如实说明并建议 `git init`（一次性操作，强烈推荐：记忆是普通文件，git 就是备份与回滚手段）。
3. **升级包**（`pipx upgrade hongzhao` / `pip install -U hongzhao`），然后确认 `hongzhao --version` 已发生变化。
4. **运行序列**：`hongzhao --root <PATH> upgrade`。不要即兴替换步骤；绝不手工编辑 `compiled/`、`render/` 下的任何内容或客户端托管块。
5. **失败即停。** 展示确切的输出，按故障排查表处理（例如 `.new` skill 冲突需要由人把关的合并决策——展示 diff，不要自行裁决），然后重新运行 `hongzhao upgrade`。
6. **报告一张简短的成功/失败表**：包版本旧→新、五个步骤的退出码，以及 `doctor` 的最后一行。如果中途出现过 `SKILL_STALE` / `BOOTSTRAP_STALE`，要提及并确认它们已消失。

## 兼容性策略

- **源数据绝不会被自动改写。** `raw/`、`config.yaml`、`registry/`、`projects/` 在历次升级中保持原样继续可用；未来的格式变更将通过显式的 `hongzhao migrate --dry-run` 发布（绝不静默进行）。
- **新的校验规则先以警告形式落地**，在后续发布中才变成错误——升级绝不会把原本全绿的记忆库变红。
- **新配置键带有默认值；改名的键在两个次要（minor）版本内保留别名。** 未知的额外键会被容忍（向前兼容）。
- **降级（downgrade）会被检测到，而不是被静默误读。** 如果派生产物由更新的引擎生成，`doctor` 会指出（`BOOTSTRAP_STALE`）；用旧引擎重新运行 `compile` 即可重新对齐。
- **1.0 之前（0.x）**：次要版本可能改变记忆库可见的格式，但遵守上述所有规则。**从 1.0 起**：遵循 semver——major（主要版本）= 需要显式迁移，minor = 仅增量新增，patch（补丁版本）= 无记忆库可见变更。
