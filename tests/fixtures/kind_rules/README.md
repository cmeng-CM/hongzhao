# kind_rules fixture）

三形态由测试在 tmp_path 构造（root 内新项目 / root 外新项目 / memory root 自身），
本目录提供作者既有条目样例（读取侧不施加 containment 的回归用）：
registry 条目 `kind: vault` + `path: ../29-CM/...`（在 memory root 之外、历史上合法），
新引擎读取时不改写、不因越界降级（「既有条目永不改写」+ 「读取侧不施加」）。
