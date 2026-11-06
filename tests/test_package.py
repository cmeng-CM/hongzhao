# 包导入与版本测试
import hongzhao


def test_version_defined():
    # 版本必须非空且可导入（ 的导入面）
    assert hongzhao.__version__
