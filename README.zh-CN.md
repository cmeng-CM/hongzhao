# hongzhao 中文简介

hongzhao 是给 AI 编程智能体用的**基于纯文本文件、由人把关**的记忆账本。智能体每次对话都会记笔记，但笔记大多烂在聊天记录里；hongzhao 把它们放进几本纯 Markdown/YAML 账本——事实主张（claim）、项目契约、知识条目——并用确定性脚本做校验与编译。没有通过把关的候选内容，永远不会进入智能体的上下文。

核心特点：**纯文件、零锁定**（一个根目录，无服务、无数据库、无云端）；**两道门**（raw 是候选区，`compile` 才生成有效视图，候选不污染上下文）；**确定性内核**（校验/编译/渲染全是可复现脚本，只有语义判断交给智能体）。冲突事实靠五种显式关系（取代、覆盖、派生、冲突、裁决）在编译期解决，而不是"最新消息说了算"。

**让 agent 替你装（一句话）**：发给你的编程智能体——

```text
Read https://github.com/cmeng-CM/hongzhao/blob/main/docs/INSTALL.md and install hongzhao for me. My client is claude_code.
```

（把 claude_code 换成你的客户端名）它按仓库安装协议执行并回报通过/失败表。

安装：`pip install hongzhao`（支持 uv / pipx；macOS 与 Linux，Python 3.9+（CI 实测 3.12/3.13），唯一运行依赖 PyYAML；Windows 原生暂不支持）。一分钟试用：

```bash
hongzhao init ~/my-memory --example
hongzhao --root ~/my-memory compile && hongzhao --root ~/my-memory validate
```

日常三命令：`validate`（结构与越界检查）、`compile`（重建派生视图）、`doctor`（客户端与产物健康检查）。项目用 `project-register` 登记契约（一个项目一份契约，注册表决定归属），长期参考资料用 `knowledge-register` 挂到知识账本。客户端接入：`bridge-install` 在指令文件注入托管块（块外内容永不改动），`skills-install` 软链四份内置技能到根目录、升级一次全端生效；自定义客户端改 config 即可。写入全部原子替换、注册先于契约落盘、崩溃可恢复，锁文件串行化并发注册。

安全面：包内没有任何联网代码；编译产物按"数据非指令"处理，渲染层对可能打断标记的内容做转义；字段限长三百、单行、拒绝控制字符——超限直接拒绝，绝不截断。排障用 `doctor`，所有问题都有稳定可 grep 的错误码与修复提示。

不做的事：不做 MCP 服务、向量检索、自动摘要、Web 界面，不做多人共享与多机同步——单写者是有意设计。

完整文档见 [docs/](docs/)（入门、设计、账本结构、客户端、安全与排障），安全模型见 [SECURITY.md](SECURITY.md)，许可证 Apache-2.0。
