"""config 放宽与 containment 测试/ +  三例 + 读取侧不施加）。

数据全合成；kind_rules 的「既有条目」样例按作者历史形态（vault + ../29-CM）构造，
验证新引擎读取不改写、不因越界降级。
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from hongzhao.core import (
    load_config,
    load_contracts,
    load_knowledge_registry,
    load_registry,
    registry_kind_for,
    resolve_knowledge_root,
    validate_knowledge_paths,
)

FIX = Path(__file__).resolve().parents[1] / "fixtures"
BASE = (FIX / "containment" / "config_base.yaml").read_text(encoding="utf-8")
OPTIONAL_OK = (FIX / "containment" / "config_optional_ok.yaml").read_text(encoding="utf-8")
MEMORY_ESCAPE = (FIX / "containment" / "config_memory_escape.yaml").read_text(encoding="utf-8")


def make_kit(base: Path, config_text: str = BASE) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.yaml").write_text(config_text, encoding="utf-8")
    (base / "raw").mkdir(exist_ok=True)
    (base / "registry").mkdir(exist_ok=True)
    return base


# ：可选键通过、未知键拒绝并列名


def test_optional_keys_accepted(tmp_path):
    kit = make_kit(tmp_path / "kit", OPTIONAL_OK)
    config = load_config(kit)  # 不抛即通过
    assert config["output"]["link_style"] == "wikilink"
    assert config["knowledge_root"] == ".."


def test_unknown_top_key_rejected_with_names(tmp_path):
    kit = make_kit(tmp_path / "kit", BASE + "\nzzz_unknown: 1\n")
    with pytest.raises(ValueError) as excinfo:
        load_config(kit)
    assert "unknown fields: zzz_unknown" in str(excinfo.value)


def test_output_validation(tmp_path):
    bad_style = make_kit(tmp_path / "a", BASE + "\noutput:\n  link_style: html\n")
    with pytest.raises(ValueError, match="link_style"):
        load_config(bad_style)
    bad_field = make_kit(tmp_path / "b", BASE + "\noutput:\n  zzz: 1\n")
    with pytest.raises(ValueError, match="output unknown fields: zzz"):
        load_config(bad_field)


#  containment 三例


def test_memory_path_escape_rejected(tmp_path):
    kit = make_kit(tmp_path / "kit", MEMORY_ESCAPE)
    with pytest.raises(ValueError, match="escapes the memory root"):
        load_config(kit)


def test_knowledge_root_outside_memory_root_is_legal(tmp_path):
    # 作者形态：knowledge_root=".."（vault 根），条目落在 knowledge_root 内、memory root 外——合法
    kit = make_kit(tmp_path / "memory", OPTIONAL_OK)
    vault = tmp_path
    notes = vault / "31-AI-Agent"
    notes.mkdir()
    (notes / "notes.md").write_text("knowledge entry", encoding="utf-8")
    (kit / "registry" / "knowledge-registry.yaml").write_text(
        "schema_version: 2\nknowledge:\n  - path: 31-AI-Agent/notes.md\n    title: t\n    topics: [a]\n    summary: s\n",
        encoding="utf-8",
    )
    registry, issues = load_knowledge_registry(kit)
    assert not issues
    assert resolve_knowledge_root(kit) == vault.resolve()
    path_issues = validate_knowledge_paths(kit, registry)
    assert path_issues == []


def test_knowledge_entry_escape_rejected(tmp_path):
    # 条目含 .. 在 load_knowledge_registry 即被拒（containment 的既有体现）
    kit = make_kit(tmp_path / "kit", OPTIONAL_OK)
    (kit / "registry" / "knowledge-registry.yaml").write_text(
        "schema_version: 2\nknowledge:\n  - path: ../escape/notes.md\n    title: t\n    topics: [a]\n    summary: s\n",
        encoding="utf-8",
    )
    _registry, issues = load_knowledge_registry(kit)
    assert any(issue.code == "KNOWLEDGE_SCHEMA" for issue in issues)


# ： kind 写值判定（单元级；命令级接线在 ）


def test_kind_rules_inside_outside_and_root_itself(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()
    inside = root / "proj" / "deep"
    inside.mkdir(parents=True)
    outside = tmp_path / "elsewhere" / "proj"
    outside.mkdir(parents=True)
    assert registry_kind_for(inside, root) == ("vault", "proj/deep")
    assert registry_kind_for(outside, root)[0] == "external"
    assert Path(registry_kind_for(outside, root)[1]).is_absolute()
    assert registry_kind_for(root, root) == ("vault", ".")


# 读取侧不施加 containment：作者既有 ../29-CM 条目不降级（ 既有不改写 +  读取侧）


def test_read_side_no_containment_for_legacy_entries(tmp_path):
    kit = make_kit(tmp_path / "memory", BASE)
    legacy_project = tmp_path / "29-CM" / "legacy"
    legacy_project.mkdir(parents=True)
    project_id = f"proj-{uuid.uuid4()}"
    (legacy_project / "project-view.md").write_text(
        f"---\nschema_version: 2\nproject_id: {project_id}\nproject_key: legacy-cm\n"
        "project_name: legacy\npurpose: p\ncurrent_state: c\nnext_action: n\n"
        "status: active\nactivation: on-demand\nentrypoints: []\nupdated_at: 2026-10-29\n---\nbody\n",
        encoding="utf-8",
    )
    (kit / "registry" / "project-registry.yaml").write_text(
        f"schema_version: 2\nprojects:\n  - project_id: {project_id}\n"
        "    location: {kind: vault, path: ../29-CM/legacy}\n"
        "    registered_at: 2026-01-01\n    last_checked_at: 2026-01-01\n",
        encoding="utf-8",
    )
    registry, registry_issues = load_registry(kit)
    assert not registry_issues  # 越界条目在读取侧不产生任何 issue
    contracts, contract_issues = load_contracts(kit, registry)
    assert not contract_issues
    assert contracts and contracts[0].metadata["project_id"] == project_id
    # 回写检查：load 路径不改写既有 kind/path
    assert registry["projects"][0]["location"]["path"] == "../29-CM/legacy"
