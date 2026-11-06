"""SOURCES 枚举放宽自检：zcode 进入校验集合，落盘字段集不变。"""
from hongzhao.core import SOURCES


def test_sources_include_zcode():
    assert SOURCES == {"claude-code", "codex", "user", "migration", "other", "zcode"}
