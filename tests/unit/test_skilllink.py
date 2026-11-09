"""skilllink 原语回归（W3）：创建/识别/删除/替换全生命周期与安全拒绝。

POSIX 上走 symlink 分支；Windows CI 上同一组用例自动覆盖 junction 分支（E5 底座）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hongzhao import skilllink


def _make_source(base: Path, name: str = "memory-write") -> Path:
    source = base / "skills" / name
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("body\n", encoding="utf-8")
    return source


def test_create_is_link_link_target_roundtrip(tmp_path):
    source = _make_source(tmp_path)
    target = tmp_path / "clients" / "skills" / "memory-write"
    target.parent.mkdir(parents=True)
    assert not skilllink.is_link(target)
    skilllink.create(target, source)
    assert skilllink.is_link(target)
    assert skilllink.link_target(target) == source.resolve()
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "body\n"  # 穿透可读


def test_remove_deletes_link_not_target(tmp_path):
    source = _make_source(tmp_path)
    target = tmp_path / "link"
    skilllink.create(target, source)
    skilllink.remove(target)
    assert not target.exists()
    assert source.is_dir() and (source / "SKILL.md").exists()  # 真源完好


def test_remove_refuses_real_directory(tmp_path):
    real = _make_source(tmp_path / "victim")
    with pytest.raises(skilllink.SkillLinkError):
        skilllink.remove(real)
    assert real.is_dir()  # 绝不删真实目录


def test_remove_missing_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        skilllink.remove(tmp_path / "nope")


def test_replace_existing_missing_target_creates(tmp_path):
    source = _make_source(tmp_path)
    target = tmp_path / "link"
    skilllink.replace_existing(target, source)  # 分支①：不存在 → create
    assert skilllink.is_link(target)


def test_replace_existing_link_rebuilds(tmp_path):
    # 分支②：已链接（调用方已判定可删，含 force 场景）→ remove + create（重复安装幂等的底座，F-02）
    source = _make_source(tmp_path)
    target = tmp_path / "link"
    skilllink.create(target, source)
    (source / "SKILL.md").write_text("updated\n", encoding="utf-8")
    skilllink.replace_existing(target, source)
    assert skilllink.is_link(target)
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "updated\n"


def test_replace_existing_replaces_broken_link(tmp_path):
    # 断链（kit 移动后）场景：lexists 命中，重建成功（E5⑥/⑧ 的原语底座）
    source = _make_source(tmp_path / "old-place")
    target = tmp_path / "link"
    skilllink.create(target, source)
    new_source = _make_source(tmp_path / "new-place")
    skilllink.replace_existing(target, new_source)
    assert skilllink.link_target(target) == new_source.resolve()


def test_replace_existing_refuses_non_link(tmp_path):
    source = _make_source(tmp_path / "src")
    real = _make_source(tmp_path / "real")
    with pytest.raises(skilllink.SkillLinkError):
        skilllink.replace_existing(real, source)
    assert real.is_dir() and (real / "SKILL.md").exists()  # 未被触碰
