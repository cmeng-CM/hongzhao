[English](README.en.md) | **简体中文**

<div align="center">

<p><img src="docs/assets/hero-hongzhao.gif" alt="hongzhao 主视觉：雪原之上，飞鹤踏雪留痕，振翅而去" width="360"></p>
<sub>名字出处「雪泥鸿爪」——飞鸿踏过雪泥，留下爪印，然后飞走。</sub>

# hongzhao

**给 AI 编程智能体的纯文本记忆账本 —— 由人把关，确定性编译，零锁定。**

[快速上手](docs/getting-started.md) · [安装](docs/INSTALL.md) · [设计](docs/design.md) · [安全模型](SECURITY.md) · [贡献指南](CONTRIBUTING.md) · [更新日志](CHANGELOG.md)

[![PyPI](https://img.shields.io/pypi/v/hongzhao?label=PyPI)](https://pypi.org/project/hongzhao/)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab)](https://pypi.org/project/hongzhao/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-8a8a8a)](#支持矩阵)
[![License](https://img.shields.io/badge/license-Apache--2.0-3da639)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-中文%C2%B7English-7016d5)](docs/)

</div>

智能体每次对话都在记笔记，而这些笔记大多烂在聊天记录里。hongzhao 给你的智能体几本纯文本账本——事实主张（claim）、项目契约、知识条目——并配确定性校验与编译。没有通过把关的候选内容，永远不会进入智能体的上下文。

- **纯文件，零锁定。**一个根目录下的 Markdown + YAML。无服务、无数据库、无云端。
- **两道门。**raw 只是候选区；`compile` 把审阅过的候选变成有效视图。候选绝不泄入上下文。
- **确定性内核。**校验、编译、渲染全是可复现脚本；只有语义判断（什么是事实、谁取代谁）属于智能体。

> **状态：预发布（v0.1）。**`v0.1.0` 之前接口可能变化。

## 让智能体替你装（一句话）

把这句话发给你的编程智能体（Claude Code、Codex CLI、ZCode、pi、dsh、OpenCode……）：

```text
Read https://github.com/cmeng-CM/hongzhao/blob/main/docs/INSTALL.md and install hongzhao for me. My client is claude_code.
```

它会按[智能体安装协议](docs/INSTALL.md#智能体安装协议)执行，并回报一张通过/失败表。想自己动手？[手动安装](docs/INSTALL.md#手动安装)只有几条命令。

## 支持矩阵

| | 状态 |
| --- | --- |
| macOS / Linux | 支持（Python 3.9+；CI 实测 3.12/3.13） |
| Windows 10+ 原生 | 支持（Python 3.9–3.13；技能挂载用目录联接 junction，无需开发者模式；网络盘/OneDrive 同步目录除外（junction 不受支持）） |
| Python | 3.9+（CI 实测 3.12/3.13；唯一运行时依赖 PyYAML） |
| 预置客户端 | Claude Code、Codex CLI、ZCode、pi、dsh（DeepSeek Harness）、OpenCode（自定义配置仍可接更多） |
| 安装 | `pip` / `uv` / `pipx` |

## 有 / 没有 hongzhao

| 关注点 | 没有 hongzhao | 有 hongzhao |
| --- | --- | --- |
| 智能体笔记 | 散落在聊天记录里，关窗即失 | 带版本、有 schema、可追溯的 raw 记录 |
| 智能体"知道"什么 | 全靠现贴进提示词 | 编译出的有效视图，按任务路由 |
| 事实冲突 | 最新消息说了算 | 显式关系（取代 / 冲突）在编译期解决 |
| 新会话冷启动 | 一切重新解释一遍 | 一个启动摘要块注入客户端指令文件 |
| 客户端自带记忆 | 各客户端各攒一份，只增不减 | `collect` 只读抽取进账本（客户端零改动，人审） |
| 离开这个工具 | —— | 删掉托管块即可；你的文件仍是纯 Markdown |

## 60 秒上手

```bash
pip install hongzhao            # 或者：uv tool install hongzhao
hongzhao init ~/my-memory --example
hongzhao --root ~/my-memory compile
hongzhao --root ~/my-memory validate
```

你现在有了一套绿色的演示记忆库：raw 笔记、编译索引、渲染好的启动摘要。打开 `~/my-memory/compiled/` 看看——每个视图都是纯 Markdown。

日常循环：

```bash
hongzhao --root ~/my-memory validate     # schema + 越界检查
hongzhao --root ~/my-memory compile      # 重建派生视图
hongzhao --root ~/my-memory doctor       # 客户端 / 托管块 / 产物健康检查
```

记忆库本身是独立 git 仓库时，每次 `compile` 之后会自动提交整个 kit（`git.auto_commit` 缺省开启，可设为 `false` 关闭）——记忆是纯文件，git 就是备份。

## 智能体安装块

把下面这段贴进智能体客户端的指令文件（或者让 `bridge-install` 替你管理这个托管块——见 [docs/clients.md](docs/clients.md)）：

```text
# hongzhao 记忆路由
memory_root: ~/my-memory
先读 compiled/bootstrap.md；任务经 compiled/effective-memory/index.md 路由。
除证据追溯外不读 raw/。写记录后运行 `hongzhao --root ~/my-memory compile`，
编译错误一律视为停止信号。
```

## 工作原理

```
raw/（事实主张，带日期）      ──compile──▶  compiled/（有效视图）
registry/ + 项目契约          ──compile──▶  render/（启动摘要、客户端块）
知识登记表                    ──compile──▶  知识地图
```

事实主张之间的五种显式关系（supersedes 取代、covers 覆盖、derived_from 提炼、conflicts 冲突、resolves 裁决）取代"最新者胜"。见 [docs/claim-schema.md](docs/claim-schema.md) 与 [docs/design.md](docs/design.md) 中的图表。

## 不做的事

- 不做 MCP 服务、向量检索、RAG、自动抽取、Web 界面。
- 不做多人共享 / 多机同步——单写者是有意设计。
- 网络盘 / OneDrive 同步目录内的记忆库不受支持（junction 无法在 reparse point 之上创建）。
- 无后台常驻——每条命令都显式，每次写入都原子。

## 为什么不用那些方案

我们刻意**没有**采用的做法（以及该用什么代替）：

- **向量库 / embedding：**文件路径和标题已经足够为编程智能体路由；瓶颈从来不是检索质量，而是审阅纪律。
- **每轮自动摘要：**未经审阅的摘要正是记忆腐烂的方式；hongzhao 让候选显式化并逐条把关。
- **服务 / API：**一个不能 grep、不能 diff、不能用 git 备份的记忆，不是你的记忆。
- **内嵌数据库：**在这个数据规模下，合并冲突的可解性与纯文本可迁移性胜过查询能力。

---

完整文档（中文）：[docs/](docs/)；English docs: [docs/en/](docs/en/)。安全模型：[SECURITY.md](SECURITY.md)。贡献指南（需 DCO 签名）：[CONTRIBUTING.md](CONTRIBUTING.md)。

许可证：Apache-2.0，见 [LICENSE](LICENSE)。
