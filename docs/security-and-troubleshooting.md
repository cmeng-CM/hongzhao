# 安全与排障

[English](en/security-and-troubleshooting.md) | **简体中文**

## 安全模型（摘要——全文见 [SECURITY.md](../SECURITY.md)）

- **无网络。** 本包不含任何网络代码；不会向任何地方发送任何内容。
- **是数据，不是指令。** 编译视图内嵌一条声明，标明其内容是数据；渲染时会转义可能逃出 bootstrap 块或伪造标记的结构（`@` 前缀行、形似标记的标签）。编译器假定 raw 笔记可能包含恶意文本，并将其渲染为无害内容。
- **以字段约束做注入防御。** 不超过 300 字符、单行、无控制字符——违反即拒绝，绝不截断。一条无法用单行 grep 检索到的断言（claim）只是笔记，而非断言。
- **围栏（越界约束）。** 树内写入始终保持在 root 之下；知识路径始终保持在 `knowledge_root` 之下；符号链接被拒绝用作 root，也禁止出现在 skill 源内部。
- **原子写入，崩溃安全的顺序。** 先写注册表（registry）再写契约（contract）；每个文件都通过临时文件 + 替换的方式写入；`<root>/.hongzhao.lock`（flock）跨进程串行化注册。
- **用于测试的故障注入。** `HONGZHAO_TEST=1` + `HONGZHAO_FAULT=<point>` 在四个关键写入边界触发崩溃——contract 测试用它证明可恢复性。

## 问题码

`validate`、`compile` 和 `doctor` 都用稳定、可 grep 的问题码（`[CODE]`）来报告。以下是你实际会遇到的：

| Code | 严重级 | 含义 / 修复 |
| --- | --- | --- |
| `CONFIG_INVALID` | error | config schema 不匹配——消息会指明具体的 key |
| `ROOT_NOT_FOUND` / `ROOT_AMBIGUOUS` | error | root 发现失败——传入 `--root` |
| `REGISTRY_BUSY` | error | 另一个进程持有锁（10 秒）——重试 |
| `CONTRACT_DUPLICATE` | error | 路径已注册到另一个 id——见 J1–J6 |
| `KEY_CONFLICT` | error | key 目录被另一个项目占用——另选一个 `--key` |
| `CONTRACT_KEY_DUPLICATE` | degraded（doctor） | 已注册的 contract 共用同一个 key——用 `project-unregister` 注销其中一个 |
| `FIELD_TOO_LONG` / `FIELD_NOT_SINGLE_LINE` / `FIELD_CONTROL_CHAR` | error | 字段超 300 字符 / 多行 / 含控制字符——编辑 raw 记录（拒绝，绝不截断） |
| `FIELD_VALUE` | error | 字段值非法（枚举、类型）——编辑 raw 记录 |
| `LEGACY_MARKER` | warning | 客户端文件仍带有旧世代（old-generation）的块——执行 `migrate-bridge all` |
| `BRIDGE_STALE` / `SKILL_MISSING` / `SKILLS_CONFIG` | warning | `bridge-install` / `skills-install` |
| `OUTPUT_MISSING` | degraded | 编译产物缺失——运行 `compile` |
| `CONTRACT_ORPHAN` | degraded | 中央 contract 缺少 registry 条目——注销或重新注册 |
| `AUTO_COMMIT_SKIP` | warning | 自动提交被跳过——git 不在 PATH、记忆库不是 git 仓库，或嵌套在外层仓库里；见提示行说明 |
| `AUTO_COMMIT_FAILED` | warning | `git add` / `git commit` 失败——见提示行首行；编译与退出码不受影响 |

## 排查实录

**health 为 `review-needed`。** 这不是错误：某条 raw 记录正在等待审阅，或有一条纠正（correction）处于未关闭状态。`compile` 的输出会列出挂起的 id；审阅它们（编辑 raw 记录或添加一条纠正），然后重新编译。没有挂起项时，`health` 回到 `ok`。

**观察一个 degraded（降级）状态（演示）。** 展示 health 系统最快、最诚实的演示：

```bash
hongzhao init /tmp/degraded-demo --example
hongzhao --root /tmp/degraded-demo compile
rm /tmp/degraded-demo/compiled/knowledge-map.md
hongzhao --root /tmp/degraded-demo doctor; echo "exit=$?"
# degraded OUTPUT_MISSING ... knowledge-map.md — exit=1
hongzhao --root /tmp/degraded-demo compile && hongzhao --root /tmp/degraded-demo doctor
# 恢复绿色（正常），exit=0
```

编译视图在设计上就是可重建的——删除永不丢数据（事实来源是 `raw/`）。

**某个客户端不再路由记忆。** 运行 `doctor`。块过期 → `bridge-install`；skill 链接缺失 → `skills-install <client>`；你重命名了 root → 修正 `config.yaml`，然后再次运行 `doctor`（链接会重新指向）。

**注册时报 `KEY_CONFLICT`。** 另一个项目已经占用了 `projects/<key>/`。换一个不同的 `--key`，或先注销旧项目（`project-unregister` 默认是 dry-run（演练模式）；`--keep-contract` 会保留文件）。

**compile 中途崩溃。** 结构上就是安全的：派生产物最后才写入，且是原子写入。重新运行 `compile`；如果持续失败，`validate` 会点名出问题的记录。compile 从不修改 `raw/` 中的任何内容。

**恢复自检。** `hongzhao project-check <path>` 按发现顺序（先中央，后项目 root）遍历，并告诉你某个路径映射到哪个 contract——当归属（ownership）看起来不对时，这是第一个该运行的命令。
