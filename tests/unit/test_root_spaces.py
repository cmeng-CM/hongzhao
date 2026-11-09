"""W5（D-W9/E13）：托管块反查支持含空格路径 + 块外 @ 行不参与匹配。"""
from __future__ import annotations

from pathlib import Path

import yaml

from hongzhao import root as rootmod

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _make_kit(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load((FIX / "containment" / "config_base.yaml").read_text(encoding="utf-8"))
    (base / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (base / "raw").mkdir(exist_ok=True)
    (base / "registry").mkdir(exist_ok=True)
    (base / "registry" / "project-registry.yaml").write_text("schema_version: 2\nprojects: []\n", encoding="utf-8")
    (base / "registry" / "knowledge-registry.yaml").write_text("schema_version: 2\nknowledge: []\n", encoding="utf-8")
    return base


def test_bridge_reverse_lookup_with_spaces(tmp_path, monkeypatch):
    # E13：含空格目录（Windows 常见用户名形态）下，import 模式反查不截断
    kit = _make_kit(tmp_path / "Test User" / "hongzhao kit")
    snap = kit / "render"
    snap.mkdir(exist_ok=True)
    (snap / "bootstrap.md").write_text("managed", encoding="utf-8")
    bridge_file = tmp_path / "client.md"
    bootstrap = snap / "bootstrap.md"
    bridge_file.write_text(
        f"<!-- hongzhao:start -->\n@{bootstrap}\n<!-- hongzhao:end -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rootmod, "PRESET_BRIDGE_PATHS", (str(bridge_file),))
    root, source = rootmod.discover_root()
    assert root == kit.resolve()
    assert source == "bridge"


def test_at_line_outside_block_ignored(tmp_path, monkeypatch):
    # W5 收紧：块外用户自有 @ 行不参与反查（即便它指向有效 kit）
    kit = _make_kit(tmp_path / "kit")
    snap = kit / "render"
    snap.mkdir(exist_ok=True)
    (snap / "bootstrap.md").write_text("managed", encoding="utf-8")
    bridge_file = tmp_path / "client.md"
    bridge_file.write_text(
        f"@{snap / 'bootstrap.md'}\nuser notes\n<!-- hongzhao:start -->\n"
        f"inline only\n<!-- hongzhao:end -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rootmod, "PRESET_BRIDGE_PATHS", (str(bridge_file),))
    # 块内无 @ 行、无 inline frontmatter → 反查不命中（不因块外 @ 误判）
    result = rootmod._managed_root_from_bridge_file(bridge_file)
    assert result is None
