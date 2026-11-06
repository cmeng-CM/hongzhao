"""manifest 三态升级测试）：未修改→覆盖；已修改→.new；manifest 缺失→全部 .new；
--force→覆盖并重写；二次安装不再产生 .new；--manifest-only 只写 manifest。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from hongzhao import __version__, bridge

FIX = Path(__file__).resolve().parents[1] / "fixtures"
BASE_CONFIG = (FIX / "containment" / "config_base.yaml").read_text(encoding="utf-8")


def make_kit(tmp: Path) -> Path:
    kit = tmp / "memory"
    kit.mkdir(parents=True, exist_ok=True)
    (kit / "config.yaml").write_text(BASE_CONFIG, encoding="utf-8")
    (kit / "raw").mkdir()
    (kit / "registry").mkdir()
    (kit / "registry" / "project-registry.yaml").write_text("schema_version: 2\nprojects: []\n", encoding="utf-8")
    (kit / "registry" / "knowledge-registry.yaml").write_text("schema_version: 2\nknowledge: []\n", encoding="utf-8")
    return kit


def _package_bytes() -> dict[str, bytes]:
    return {relative: source.read_bytes() for source, relative in bridge._package_tree()}


def test_manifest_four_states_and_second_install(tmp_path, capsys):
    kit = make_kit(tmp_path)
    package = _package_bytes()
    # ① 全新安装（含 manifest 写入）
    assert bridge.cmd_skills_install(kit, "all", manifest_only=False) in (0, 1)  # 无 enabled 客户端 → 阶段②空
    manifest = yaml.safe_load((kit / ".hongzhao-manifest.json").read_text(encoding="utf-8"))
    file_keys = {k for k in manifest if not k.startswith("_")}
    assert file_keys == set(package)  # 文件键集=包清单；`_` 前缀是版本元数据
    assert manifest["_synced_with"] == __version__  # 升级偏斜检测（doctor SKILL_STALE）
    for relative in file_keys:
        assert (kit / relative).read_bytes() == package[relative]
    # ② 用户改过根内文件 → .new、原文件保留
    target = kit / "skills" / "memory-write" / "SKILL.md"
    original = target.read_bytes()
    target.write_bytes(b"user customized\n")
    bridge.cmd_skills_install(kit, "all")
    assert target.read_bytes() == b"user customized\n"  # 未覆盖
    assert (kit / "skills" / "memory-write" / "SKILL.md.new").read_bytes() == original
    # ③ --force → 覆盖并重写 manifest
    assert bridge.cmd_skills_install(kit, "all", force=True) in (0, 1)
    assert target.read_bytes() == package["skills/memory-write/SKILL.md"]
    manifest = yaml.safe_load((kit / ".hongzhao-manifest.json").read_text(encoding="utf-8"))
    # ④ 二次安装不再产生 .new
    (kit / "skills" / "memory-write" / "SKILL.md.new").unlink()
    bridge.cmd_skills_install(kit, "all")
    assert not (kit / "skills" / "memory-write" / "SKILL.md.new").exists()


def test_manifest_missing_reports_and_writes_new(tmp_path, capsys):
    kit = make_kit(tmp_path)
    package = _package_bytes()
    # 预置根内文件（用户改过形态）但无 manifest → 无法校验：全部写 .new 不覆盖
    for relative, content in package.items():
        path = kit / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"existing-user-content\n")
    code = bridge.cmd_skills_install(kit, "all")
    out = capsys.readouterr().out
    assert "SKILL_MODIFIED" in out or "SKILL_DEPRECATED" in out
    assert (kit / "skills" / "memory-write" / "SKILL.md").read_bytes() == b"existing-user-content\n"
    assert (kit / "skills" / "memory-write" / "SKILL.md.new").read_bytes() == package["skills/memory-write/SKILL.md"]


def test_manifest_only_writes_manifest_without_touching_files(tmp_path):
    kit = make_kit(tmp_path)
    package = bridge._package_tree()
    # 根内一份用户改过的文件
    first_rel = package[0][1]
    target = kit / first_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"keep me\n")
    bridge.cmd_skills_install(kit, "all", manifest_only=True)
    assert target.read_bytes() == b"keep me\n"  # 不覆盖 skill 文件
    assert not list(kit.rglob("*.new"))  # 全程不写 .new
    absent_rel = next(rel for _src, rel in bridge._package_tree() if rel != first_rel)
    absent = kit / absent_rel
    assert not absent.exists()  # 缺席文件不安装
    import hashlib
    manifest = yaml.safe_load((kit / ".hongzhao-manifest.json").read_text(encoding="utf-8"))
    assert manifest[first_rel] == hashlib.sha256(b"keep me\n").hexdigest()  # 按当前内容记录
    assert absent_rel not in manifest  # 缺席不入 manifest
