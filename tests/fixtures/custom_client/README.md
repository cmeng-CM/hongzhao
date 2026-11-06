# custom_client fixture）

用途：自定义客户端（config 中任意名字，如 `dsh`）安装判定的测试材料说明。
判定=bridge_path 父目录存在；测试在 tmp_path 按 `bridge_path 指向的父目录存在/不存在`
两态构造（见 tests/unit/test_bridge.py::test_custom_client_explicit_and_all），
本目录不承载运行时数据。
