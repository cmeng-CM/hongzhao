"""桥接生命周期测试（ 外来软链 /  迁移七组 /  卸载边界 /  自定义客户端）。

全部在 tmp_path 构造最小记忆库与假客户端文件；检测结果通过 monkeypatch 注入。
"""
from __future__ import annotations

from pathlib import Path

import shutil

import pytest
import yaml

from hongzhao import bridge, skilllink
from hongzhao.core import load_config
from hongzhao.render import compile_all

NEW_S = bridge.MANAGED_START
NEW_E = bridge.MANAGED_END
OLD_S = bridge.LEGACY_START
OLD_E = bridge.LEGACY_END

BASE_CONFIG = (Path(__file__).resolve().parents[1] / "fixtures" / "containment" / "config_base.yaml").read_text(encoding="utf-8")

RECORD = """---
schema_version: 2
id: mem-44444444-4444-4444-8444-444444444444
created: 2026-10-29
source: user
topic: bridge-test
kind: memory
scope: global
activation: on-demand
record_type: source
summary: Bridge test record.
compile_status: done
---

body
"""


def make_kit(tmp: Path, clients_yaml: str | None = None) -> Path:
    kit = tmp / "memory"
    kit.mkdir(parents=True, exist_ok=True)
    config = BASE_CONFIG
    if clients_yaml is not None:
        # YAML 级替换客户端段（不依赖 fixture 中的具体路径文本）
        import yaml as _yaml
        data = _yaml.safe_load(config)
        data["clients"] = _yaml.safe_load(clients_yaml)
        config = _yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    (kit / "config.yaml").write_text(config, encoding="utf-8")
    (kit / "raw").mkdir(exist_ok=True)
    (kit / "raw" / "record.md").write_text(RECORD, encoding="utf-8")
    (kit / "registry").mkdir(exist_ok=True)
    (kit / "registry" / "project-registry.yaml").write_text("schema_version: 2\nprojects: []\n", encoding="utf-8")
    (kit / "registry" / "knowledge-registry.yaml").write_text("schema_version: 2\nknowledge: []\n", encoding="utf-8")
    # skills/templates 根副本 + manifest（供软链与同步）
    skills = kit / "skills" / "memory-write"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("stub\n", encoding="utf-8")
    compile_all(kit)
    return kit


def client_dirs(tmp: Path, name: str = "cc") -> tuple[Path, Path]:
    bridge_file = tmp / "clients" / name / "RULES.md"
    skills_root = tmp / "clients" / name / "skills"
    bridge_file.parent.mkdir(parents=True, exist_ok=True)
    skills_root.mkdir(parents=True, exist_ok=True)
    return bridge_file, skills_root


def kit_with_client(tmp: Path, enabled: bool, bridge_text: str = "", name: str = "cc", mode: str = "inline") -> tuple[Path, Path]:
    bridge_file, skills_root = client_dirs(tmp, name)
    bridge_file.write_text(bridge_text, encoding="utf-8")
    clients_yaml = (
        f"  {name}:\n    enabled: {str(enabled).lower()}\n"
        f"    bridge_path: {bridge_file}\n    skills_root: {skills_root}\n    mode: {mode}\n"
    )
    kit = make_kit(tmp / "memory", clients_yaml)
    return kit, bridge_file


@pytest.fixture(autouse=True)
def _detect_yes(monkeypatch):
    monkeypatch.setattr(bridge, "client_installed", lambda name, settings: True)


# ：外来软链跳过不删；--force 才覆盖


def test_foreign_symlink_skipped_then_forced(tmp_path):
    kit, _bf = kit_with_client(tmp_path, True)
    config = load_config(kit)
    skills_root = Path(str(config["clients"]["cc"]["skills_root"]))
    foreign_target = tmp_path / "foreign" / "memory-write"
    foreign_target.mkdir(parents=True)
    (foreign_target / "SKILL.md").write_text("foreign\n", encoding="utf-8")
    link = skills_root / "memory-write"
    skilllink.create(link, foreign_target)  # 测试侧建链走原语（F-09，跨平台）
    assert bridge.cmd_skills_install(kit, "cc") == 1  # SKILL_CONFLICT 跳过
    assert link.resolve() == foreign_target.resolve()  # 未删除未改指
    assert bridge.cmd_skills_install(kit, "cc", force=True) == 0  # --force 覆盖
    assert link.resolve() == (kit / "skills" / "memory-write").resolve()


# ：migrate 七组


def _has_old(text: str) -> bool:
    return OLD_S in text


def _has_new(text: str) -> bool:
    return NEW_S in text


def test_migrate_enabled_old_only_replaced(tmp_path):
    kit, bf = kit_with_client(tmp_path, True, bridge_text=f"{OLD_S}\nold\n{OLD_E}\n")
    assert bridge.cmd_migrate_bridge(kit) == 0
    text = bf.read_text(encoding="utf-8")
    assert not _has_old(text) and _has_new(text)


def test_migrate_enabled_old_and_new_removes_old(tmp_path):
    kit, bf = kit_with_client(tmp_path, True, bridge_text=f"{OLD_S}\nold\n{OLD_E}\n\n{NEW_S}\nkeep\n{NEW_E}\n")
    assert bridge.cmd_migrate_bridge(kit) == 0
    text = bf.read_text(encoding="utf-8")
    assert not _has_old(text) and "keep" in text


def test_migrate_enabled_new_only_refreshes(tmp_path):
    kit, bf = kit_with_client(tmp_path, True, bridge_text=f"{NEW_S}\nstale\n{NEW_E}\n")
    assert bridge.cmd_migrate_bridge(kit) == 0
    text = bf.read_text(encoding="utf-8")
    assert "stale" not in text and "<hongzhao-bootstrap>" in text


def test_migrate_multiple_same_generation_refused(tmp_path):
    kit, bf = kit_with_client(tmp_path, True, bridge_text=f"{OLD_S}\na\n{OLD_E}\n{OLD_S}\nb\n{OLD_E}\n")
    assert bridge.cmd_migrate_bridge(kit) == 1
    assert _has_old(bf.read_text(encoding="utf-8"))  # 未动


def test_migrate_disabled_old_removed_no_new(tmp_path):
    kit, bf = kit_with_client(tmp_path, False, bridge_text=f"{OLD_S}\nold\n{OLD_E}\n")
    assert bridge.cmd_migrate_bridge(kit) == 0
    text = bf.read_text(encoding="utf-8")
    assert not _has_old(text) and not _has_new(text)


def test_migrate_disabled_old_and_new_keeps_new_unrefreshed(tmp_path):
    kit, bf = kit_with_client(tmp_path, False, bridge_text=f"{OLD_S}\nold\n{OLD_E}\n\n{NEW_S}\nkeep-as-is\n{NEW_E}\n")
    assert bridge.cmd_migrate_bridge(kit) == 0
    text = bf.read_text(encoding="utf-8")
    assert not _has_old(text) and "keep-as-is" in text


def test_migrate_disabled_new_only_untouched(tmp_path):
    kit, bf = kit_with_client(tmp_path, False, bridge_text=f"{NEW_S}\nkeep\n{NEW_E}\n")
    assert bridge.cmd_migrate_bridge(kit) == 0
    assert bf.read_text(encoding="utf-8") == f"{NEW_S}\nkeep\n{NEW_E}\n"


# ：uninstall 边界


def test_uninstall_dry_run_then_yes(tmp_path):
    kit, bf = kit_with_client(tmp_path, True, bridge_text=f"{OLD_S}\nold\n{OLD_E}\n\n{NEW_S}\nnew\n{NEW_E}\n")
    config = load_config(kit)
    skills_root = Path(str(config["clients"]["cc"]["skills_root"]))
    link = skills_root / "memory-write"
    skilllink.create(link, kit / "skills" / "memory-write")  # 测试侧建链走原语（F-09）
    # dry-run：零改动
    assert bridge.cmd_uninstall(kit, yes=False) == 0
    assert NEW_S in bf.read_text(encoding="utf-8") and link.is_symlink()
    # --yes：删两代块与 root/skills 内软链；非软链不动；记忆根保留
    plain_dir = skills_root / "not-a-link"
    plain_dir.mkdir()
    (plain_dir / "x.txt").write_text("user data\n", encoding="utf-8")
    assert bridge.cmd_uninstall(kit, yes=True) == 0
    text = bf.read_text(encoding="utf-8")
    assert NEW_S not in text and OLD_S not in text
    assert not link.exists()
    assert plain_dir.is_dir() and (plain_dir / "x.txt").exists()  # 绝不 rmtree 非软链
    assert (kit / "config.yaml").exists()  # 不删记忆根


# ：自定义客户端安装判定两态


def test_custom_client_explicit_and_all(tmp_path, monkeypatch):
    # 本例用真实  判定（自定义客户端=bridge_path 父目录存在），覆盖 autouse 桩
    monkeypatch.setattr(
        bridge, "client_installed",
        lambda name, settings: Path(str(settings["bridge_path"])).expanduser().parent.is_dir(),
    )
    cc_bridge, _cc_skills = client_dirs(tmp_path, "cc")
    bridge_file, _skills = client_dirs(tmp_path, "dsh")
    shutil.rmtree(bridge_file.parent)  # dsh 目录整体移除 → 未安装
    clients_yaml = (
        f"  cc:\n    enabled: true\n    bridge_path: {cc_bridge}\n"
        f"    skills_root: {_cc_skills}\n    mode: inline\n"
        f"  dsh:\n    enabled: true\n    bridge_path: {bridge_file}\n"
        f"    skills_root: {_skills}\n    mode: inline\n"
    )
    kit = make_kit(tmp_path / "memory", clients_yaml)
    cc_bridge.write_text("", encoding="utf-8")
    # dsh 的 bridge_path 父目录已整体移除 → 未安装
    # 显式点名：CLIENT_NOT_INSTALLED、不写任何文件、exit 1
    assert bridge.cmd_bridge_install(kit, "dsh") == 1
    assert not bridge_file.exists()
    # all：跳过 + warning，其余照常，整体 exit 0
    assert bridge.cmd_bridge_install(kit, "all") == 0
    assert not bridge_file.exists()
    assert cc_bridge.read_text(encoding="utf-8").count(NEW_S) == 1
    # 父目录出现后（ 判安装）：all 正常写入
    bridge_file.parent.mkdir(parents=True, exist_ok=True)
    bridge_file.write_text("", encoding="utf-8")
    assert bridge.cmd_bridge_install(kit, "all") == 0
    assert NEW_S in bridge_file.read_text(encoding="utf-8")


def test_doctor_levels_and_line_format(tmp_path):
    kit, bf = kit_with_client(tmp_path, True, bridge_text=f"{OLD_S}\nold\n{OLD_E}\n")
    config = load_config(kit)
    # enabled 客户端缺少 skills 软链 → warning；旧块 → LEGACY_MARKER warning；全部 warning → exit 0
    code = bridge.cmd_doctor(kit)
    assert code == 0
    # 删除派生产物 → OUTPUT_MISSING degraded → exit 1
    (kit / "compiled" / "current-state.md").unlink()
    assert bridge.cmd_doctor(kit) == 1
