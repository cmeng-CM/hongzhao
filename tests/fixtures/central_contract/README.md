# central_contract fixture、）

用途：central 契约正文链接（恒 markdown）的测试材料。
- `projects/mykey/project-view.md`：central 契约样例（frontmatter 键集与冻结 schema 一致）。
- 目标文件由测试在 tmp_path 按本目录结构复制构造（避免真实路径依赖）；
  链接断言按 ：`relpath(目标, 契约所在目录)` 可解析。
 实现 central 契约生成时，本 fixture 同时作为  命令级用例的输入基线。
