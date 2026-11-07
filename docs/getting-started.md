# 快速上手

[English](en/getting-started.md) | **简体中文**

五分钟内从零搭建一个可用的记忆库。

## 安装

需要 macOS / Linux 和 Python 3.9+（CI 在 3.12/3.13 上测试通过）；v0.1 不支持 Windows 原生——`init` 会快速失败。

```bash
pip install hongzhao          # 或者：uv tool install hongzhao / pipx install hongzhao
hongzhao --version
```

## 绿色演示（示例套件，推荐首次运行）

```bash
hongzhao init ~/my-memory --example
hongzhao --root ~/my-memory compile
hongzhao --root ~/my-memory validate
```

`--example` 会植入一个小型演示数据集（一条用户画像事实主张、一条纠正、一条已被取代的笔记）。`compile` 之后，查看：

- `compiled/effective-memory/` —— 按 global / non-project / per-project 划分的有效视图
- `compiled/effective-memory/index.md` —— Agent 最先读取的路由索引
- `compiled/current-state.md` —— 一屏的项目状态
- `compiled/last-compile-diff.md` —— 本次编译相对上一次改动了什么
- `render/bootstrap.md` —— 会被注入到客户端文件中的那个块

在演示记忆库上，`validate` 退出码为 0 且没有任何问题。这就是“绿色场景”。

## 日常循环

1. **捕获。** Agent 在 `raw/` 下写一条 raw 记录（见 [事实主张 Schema](claim-schema.md)）——也可以由你手写一条。
2. **把关。** 由你审阅这条候选（raw 记录*尚未*生效）。
3. **编译。** `hongzhao --root ~/my-memory compile` 重建所有派生视图。
4. **检查。** `hongzhao --root ~/my-memory validate && hongzhao --root ~/my-memory doctor`。

## 注册项目

项目契约（project contract）是单个项目记忆作用域（scope）的唯一事实源：

```bash
hongzhao --root ~/my-memory project-register ~/code/my-app \
  --purpose "Payment service" --current-state "Beta" \
  --next-action "Retry hardening" --key my-app
hongzhao --root ~/my-memory project-check ~/code/my-app
```

`project-register` 会写入一条注册表条目，并在 `projects/<key>/project-view.md` 下写入一份集中契约（J1–J6 生命周期；见 [设计](design.md)）。`project-unregister` 默认是 dry-run（演练模式）。

## 注册知识

长期参考材料（文档、规范、复盘）存放在你的知识根目录（knowledge root）中，由知识登记表（knowledge registry）引用：

```bash
hongzhao --root ~/my-memory knowledge-register docs/rust-async.md \
  --title "Rust async book" --topic rust \
  --summary "Async internals reference used for the runtime rewrite"
```

`path` 相对于知识根目录（知识根目录默认为记忆根目录本身；在 config 中设置 `knowledge_root`，可把参考材料保持在账本之外）。`--topic` 可以重复。目标文件必须已经存在。

## 客户端（可选）

启用某个客户端，即可在它的指令文件中获得一个托管的启动摘要块（bootstrap block），并让打包技能以软链接方式接入：

```bash
hongzhao --root ~/my-memory bridge-install
hongzhao --root ~/my-memory skills-install all
hongzhao --root ~/my-memory doctor
```

完整生命周期见 [客户端](clients.md)。

## 配置

记忆库通过 `<root>/config.yaml` 配置。各键如下（未知的顶层键会被拒绝）：

| 键 | 含义 | 默认值 |
| --- | --- | --- |
| `schema_version` | 配置 schema，必须为 `2` | — |
| `paths` | root 下的 8 个相对路径（raw/compiled/registry/...） | 常规布局 |
| `skills` | 要安装的打包技能 | 捆绑集 |
| `clients` | 各客户端的设置（见下文） | 全部禁用（`init --client` 会启用检测到的客户端） |
| `output` | 可选的渲染选项（`link_style`、`link_prefix`） | markdown 链接 |
| `knowledge_root` | 知识路径的基础目录，相对于 root | `.` |

每个客户端的设置——恰好四个键（`enabled`、`bridge_path`、`skills_root`、`mode`）；未知或缺失的键会被拒绝并报 `CONFIG_INVALID`。

两条围栏规则在保护你：记忆树内的路径必须留在根目录之内；知识路径必须留在 `knowledge_root` 之内。两者都在写入时强制执行，而非读取时。

## FAQ

**问：`hongzhao` 会到哪里找我的记忆根目录？**
按顺序有四个来源：`--root`，然后是 `$HONGZHAO_ROOT`，然后是工作目录（向上最多五层找 `config.yaml`），然后是预置客户端指令文件中的托管块（反向查找）。候选校验失败即硬错误——绝不静默回退。`hongzhao root --json` 会显示最终命中的是哪一个。

**问：如果我手动编辑了编译产物，会怎么样？**
不会立刻出问题，但下一次 `compile` 会把它覆盖，`doctor`/金丝雀（canary）比对也会把漂移标记出来。编译和渲染产物都是可重建的视图；请改为编辑 `raw/`。

**问：两个 Agent 能同时写入吗？**
注册表的写入会在 `<root>/.hongzhao.lock` 上加排他 `flock`（10 秒超时，发生竞争时报 `REGISTRY_BUSY`）。这套记忆库在设计上仍是单写者（single-writer）——并发注册是安全的，但并不鼓励并发写笔记。

**问：怎么把它整套卸载？**
`hongzhao --root ~/my-memory uninstall --yes` 会移除托管块和技能软链接（默认 dry-run；不存在 `--delete-data` 这个参数——根目录请你自己删除）。

**问：我的数据会被发送到任何地方吗？**
不会。本包完全不含网络代码（参见 [安全模型](../SECURITY.md)）。

**问：为什么我的 health 是 `review-needed`？**
有一条 raw 记录在等待审阅（或有一条纠正处于未关闭状态）。这是一个提示，不是错误；解决办法是审阅那条事实主张，然后重新编译。见 [安全与排障](security-and-troubleshooting.md)。
