# 客户端

[English](en/clients.md) | **简体中文**

**客户端**（client）是带有指令文件（instruction file）的智能体宿主，例如 Claude Code 的 `CLAUDE.md`、Codex CLI 的 `AGENTS.md`、ZCode 的 `AGENTS.md` 等。hongzhao 可以向该文件注入一个托管的**启动摘要块**（bootstrap block），并把打包技能以软链接（symlink）方式接入客户端的技能目录（skills directory）。

## 预置客户端（v0.1）

| 客户端 | 指令文件 | 检测位置 |
| --- | --- | --- |
| `claude_code` | `~/.claude/CLAUDE.md` | `~/.claude` |
| `codex` | `~/.codex/AGENTS.md` | `~/.codex` |
| `zcode` | `~/.zcode/AGENTS.md` | `~/.zcode` |

`hongzhao init --client claude_code --client codex`（每个客户端重复一次该参数）会检测列出的客户端中哪些实际存在，并只启用存在的那些（init 绝不自动安装；它只负责配置）。自定义客户端（custom client）只是普通的配置条目——你在 `config.yaml` 中自行设置 `bridge_path` 和 `skills_root`。

## 托管块

该块由 `hongzhao:start` / `hongzhao:end` 标记界定：

```text
<!-- hongzhao:start (managed; edit outside the markers) -->
……由 render/bootstrap.md 渲染出的启动摘要……
<!-- hongzhao:end -->
```

- `bridge-install` 插入或刷新该块；标记之外的内容绝不改动。它**不会**触碰旧一代（legacy）的 `agent-memory` 块——迁移旧一代块是 `migrate-bridge` 的职责（可为全部客户端一次性运行；在那之前两代块可能并存）。
- `uninstall`（默认 dry-run）移除该块。标记之外的一切内容逐字节原样保留。
- `doctor` 校验每个已启用的客户端：块内容与当前启动摘要一致，且技能软链接均解析到 `<root>/skills` 之内。

## 技能

`skills-install all`（按客户端：`skills-install claude_code`）把打包的技能/模板复制到 `<root>/skills/`，并建立软链接 `<client.skills_root>/<skill>` → `<root>/skills/<skill>`——唯一事实源（single source of truth），升级一次，所有客户端同步更新。保护机制：

- 指向别处的软链接会报 `SKILL_CONFLICT`（可用 `--force` 覆盖），
- 外来（非软链接）目录绝不改动，
- `uninstall` 只移除解析后位于 `<root>/skills` 之内的软链接。

清单（manifest，`.hongzhao-manifest.json`）固定内容哈希（content hash），使升级成为显式操作：`skills-install --manifest-only` 只记录当前哈希、不改动任何文件（切换流程会用到）。

## 刷新入口

所有会改变启动摘要内容的路径（bridge-install、knowledge-register、uninstall）都汇聚到同一个函数——只要命令成功执行，该块绝不会过期。

## 诊断客户端

`hongzhao doctor` 输出带严重级（severity）标签的行，仅当存在 `degraded` 行时才以退出码 1 结束（仅有 warning 时退出码保持为 0）：

```text
warning BRIDGE_STALE claude_code ~/.claude/CLAUDE.md managed block drifted; run hongzhao bridge-install
warning SKILL_MISSING codex ~/.codex/skills/memory-compile skill symlink missing: memory-compile
warning LEGACY_MARKER claude_code ~/.claude/CLAUDE.md legacy agent-memory block present; run hongzhao migrate-bridge all
degraded OUTPUT_MISSING - /path/to/compiled/knowledge-map.md derived output missing; run hongzhao compile
```

每一行 degraded/warning 都会指明受影响的客户端和文件；修复命令即该行消息中所示的那条（如有给出）。完整的问题代码表见[安全与故障排除](security-and-troubleshooting.md)。

## 共享技能目录（一套软链接，多个客户端）

`skills_root` 按客户端独立设置。在多个智能体读取同一个共享技能目录（例如 `~/.agents/skills`）的机器上，把每个非 Claude 客户端的 `skills_root` 都指向该共享目录——这样一次 `skills-install` 建立的一套软链接即可覆盖它们全部，同一个技能也绝不会安装两次：

```yaml
clients:
  claude_code:
    skills_root: ~/.claude/skills    # Claude 专用
  zcode:
    skills_root: ~/.agents/skills    # 所有非 Claude 智能体共享
  codex:
    skills_root: ~/.agents/skills    # 同一个共享目录
```

桥接（bridge）与技能相互独立：`bridge_path` 是每个客户端一份的规则文件（安装时按客户端选择），而技能的源只需与不同技能目录的数量一样多。如果某个客户端自带的技能目录你并不使用，就不要在那里安装任何东西——未使用的客户端完全不需要条目。
