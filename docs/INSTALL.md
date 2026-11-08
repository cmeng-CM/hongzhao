# 安装 hongzhao

[English](en/INSTALL.md) | **简体中文**

两类读者，一份文件。人类：[手动安装](#手动安装)里的三条命令。AI 智能体：你的协议是[智能体安装协议](#智能体安装协议)——当用户让你安装 hongzhao 时，照它执行。

## 让 AI 智能体替你装（一句话）

把这句话发给你的编程智能体（Claude Code、Codex CLI、ZCode……）：

```text
Read https://github.com/cmeng-CM/hongzhao/blob/main/docs/INSTALL.md and install hongzhao for me. My client is claude_code.
```

把 `claude_code` 换成你的客户端（`codex`、`zcode`，可多个）。智能体会执行下面的协议，并报告一张通过/失败表。

## 手动安装

要求 macOS 或 Linux，以及 Python 3.9+（CI 在 3.12/3.13 上测试）。v0.1 不支持原生 Windows——`init` 会快速失败，而不是假装成功。

```bash
pip install hongzhao          # 或者：uv tool install hongzhao / pipx install hongzhao
hongzhao init ~/hongzhao --client claude_code   # 每个客户端重复一次 --client
hongzhao --root ~/hongzhao compile              # 必须在 bridge-install 之前运行
hongzhao --root ~/hongzhao bridge-install claude_code
hongzhao --root ~/hongzhao skills-install claude_code
hongzhao --root ~/hongzhao doctor               # 预期：doctor: ok，退出码 0
```

---

## 智能体安装协议

你是 AI 编程智能体，用户要求你安装 hongzhao——一个面向智能体的纯文件记忆账本（memory ledger）。严格按本协议执行。**基本规则：**

1. **任何改动之前先检查。**检查是否已有记忆库（memory kit，如 `~/hongzhao` 或任何 `hongzhao/config.yaml`）、客户端文件中是否已有托管块（managed block，`hongzhao:start` 标记）或遗留的 `agent-memory` 块、客户端 skills 目录中是否已有软连接。安装**之前**报告你的发现。绝不覆盖、合并或删除已存在的任何内容——一旦有冲突，停下并报告。
2. **使用这些精确命令**（只按用户指定的路径调整）。不要即兴替换方案。`--client` 是**可重复的旗标**（`--client claude_code --client codex`）；逗号拼接的值（`--client a,b`）无效。`compile` 必须在 `bridge-install` **之前**运行：托管块的内容来自编译后的启动摘要（bootstrap）。
3. **绝不手工编辑客户端文件。**托管块只由 `bridge-install` 维护。`hongzhao:start/end` 标记之外的内容必须保持逐字节一致。同样，绝不手工编辑 `compiled/` 或 `render/` 下的任何内容——它们由 `compile` 重建。
4. **以验证收尾**（见下），并向用户展示一份简短的通过/失败报告。任一步骤失败时：停下，展示确切的命令输出，并按故障排查表给出修复建议——不要硬闯过失败。
5. **两个选择由用户做主，不由你。**记忆库位置和要接线的客户端集合，必须通过客户端的原生选择对话框（如 AskUserQuestion）询问。如果你的运行环境没有对话框工具，就用普通聊天提问并等待回复。绝不静默假设默认值——默认值只在用户明确接受时才适用（空回答 = 接受默认值）。

### 步骤

```bash
# 0. 前置条件（继续之前先报告结果）
python3 --version            # 需要 >= 3.9；原生 Windows → 停止（v0.1 不支持）

# 1. 安装（选用第一个可用渠道；报告你用了哪个）
pipx install hongzhao        # 备选：python3 -m pip install --user hongzhao
                             # 备选：uv tool install hongzhao
hongzhao --version

# 2. 探测已安装的客户端（询问之前先报告发现结果）
#    探测按预设客户端 2-of-3 判定：PATH 上有可执行文件 / 配置目录 /
#    版本命令。快速检查（>=2 个信号存在即算检测到该客户端）：
command -v claude || true; [ -d ~/.claude ] && echo "claude_code signals"
command -v codex  || true; [ -d ~/.codex ]  && echo "codex signals"
command -v zcode  || true; [ -d ~/.zcode ]  && echo "zcode signals"

# 3. 必需——询问用户（用原生对话框；没有对话框工具就用普通聊天提问；
#    等待回答，绝不替用户作答）：
#    a) 记忆库位置——提供默认值 ~/hongzhao；用户可以输入其他路径，
#       或接受默认值（空回答 = 默认值）。
#       展示对话框时附上这条指引：推荐默认值——独立目录便于用 git
#       做版本管理和备份；不要把记忆库嵌进已有的笔记仓库或代码仓库
#       （会让两个系统耦合，生成文件污染宿主历史）。记忆库是纯
#       Markdown：Obsidian 可以把它作为第二个仓库打开来浏览，因此
#       保持独立不会损失任何东西。
#    b) 接线哪些已检测到的客户端——从检测到的列表中多选
#       （一个都不选也有效：只建记忆库，不接线客户端）。
#       用户也可能坚持要某个你的检查未检测到的客户端——
#       接受它，init 之后手动启用（见故障排查）。

# 4. 按用户的选择创建记忆库（每个选择重复一次 --client；
#    用户一个都没选就省略全部 --client 旗标）
hongzhao init <PATH> --client <c1> --client <c2>
#    预期："initialized memory kit at ..."；请求了但未检测到的
#    客户端保持 enabled:false 并附带警告——这是有意设计

# 5. 编译，然后接线所选客户端
hongzhao --root <PATH> compile                   # 预期："compiled: ok"
hongzhao --root <PATH> bridge-install all        # 只会触碰已启用的客户端
hongzhao --root <PATH> skills-install all

# 6. 健康检查
hongzhao --root <PATH> doctor                    # 预期："doctor: ok"
```

### 验证（逐项报告通过/失败）

| # | 检查项 | 命令 / 预期 |
| --- | --- | --- |
| 1 | CLI 已安装 | `hongzhao --version` 打印版本号 |
| 2 | 记忆库已创建 | `~/hongzhao/config.yaml`、`raw/`、`compiled/` 存在 |
| 3 | 托管块存在 | 客户端文件恰好包含一个 `hongzhao:start` 和一个 `hongzhao:end` 标记；所有先前存在的用户内容仍在且未被改动 |
| 4 | Skills 已链接 | 客户端 skills 目录有 4 个软连接（memory-write、memory-compile、memory-project-context、work-closeout），指向 `~/hongzhao/skills/` |
| 5 | 健康检查通过 | `hongzhao --root ~/hongzhao doctor` 退出码为 0 |

### 故障排查

| 症状 | 修复 |
| --- | --- |
| bridge-install 时 `render/bootstrap.md` 缺失 | 先运行 `compile`（步骤 3 的顺序很重要） |
| `--client a,b` 被当作未知客户端拒绝 | 重复该旗标：`--client a --client b` |
| 客户端未检测到，留在 `enabled:false` | 此机器上未安装该客户端（2-of-3 探测）；先安装客户端，或编辑 `config.yaml` 设 `enabled: true` |
| `CONFIG_INVALID: client ... fields incomplete` | 客户端条目必须恰好包含 `enabled / bridge_path / skills_root / mode` |
| 文件中已有遗留 `agent-memory` 块 | 不要动它；报告并向用户提供 `hongzhao migrate-bridge all` |
| `doctor` 显示 `SKILL_MISSING` | 重新运行 `skills-install <client>` |
| skills-install 报 `SKILL_CONFLICT`：客户端 skills 目录已有链接/目录 | 已存在的 `memory-*` 条目属于另一个记忆库。与用户确认后，运行 `skills-install <client> --force` 重新指向（另一个库的文件不会被触碰） |
| `pip install --user` 报 `externally-managed-environment` 失败 | macOS Homebrew Python 阻止用户级安装；改用 `uv tool install hongzhao`，或先 `brew install pipx` |
| 运行环境没有选择对话框工具 | 两个问题都放在普通聊天里提出并等待；不要凭假设的回答继续 |
| 用户坚持要某个未检测到的客户端（如 `zcode` CLI 不在 PATH 上但 `~/.zcode` 存在） | init 之后，在 `<PATH>/config.yaml` 中把该客户端设为 `enabled: true`，再重新运行 `bridge-install all` / `skills-install all` |

### 安装完成后（告诉用户）

用户的智能体现在拥有四个记忆技能（触发短语）："记一下 / 记住" → 写入一条**候选**（candidate）笔记（编译之前什么都进不了上下文）；"编译记忆" → 语义审阅 + 重建 + 刷新客户端；"给这个项目建档" → 项目契约（project contract）；"收尾" → 会话收尾路由。首次编译审阅由用户把关：候选绝不会未经审阅就泄入上下文。

安装之后，还可以建议（每条一行，未获请求不要擅自运行）：

- **给记忆库做版本管理**：`git init <PATH>`，并在每次每周编译后提交——记忆就是纯文件；git 就是备份。记忆库是独立 git 仓库时，每次编译后会自动提交（`git.auto_commit` 缺省开启，可在 `config.yaml` 里设为 `false` 关闭）。
- **用 Obsidian 浏览**：记忆库是纯 Markdown；Obsidian → "Open folder as vault"（打开文件夹为仓库）可直接打开它（让它保持第二个仓库的身份，不要嵌进已有仓库）。
- **日后升级**：`pipx upgrade hongzhao`，然后 `hongzhao --root <PATH> upgrade`——见 [UPGRADE.md](UPGRADE.md)。

如果实际情况与本协议不符（路径、客户端、错误），灵活调整，向用户解释你的推理，且绝不硬闯过一个失败的步骤。
