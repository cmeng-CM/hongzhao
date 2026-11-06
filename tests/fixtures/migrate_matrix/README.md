# migrate_matrix fixture七行决策表）

七组形态由测试在 tmp_path 内联构造（enabled×{旧/新/旧+新/同类多个} + disabled×{旧/新/旧+新}），
见 tests/unit/test_bridge.py::test_migrate_*；本目录承载说明与标记样例，不承载运行时数据。
标记样例：旧代 `<!-- agent-memory:start/end -->`，新代 `<!-- hongzhao:start/end -->`。
