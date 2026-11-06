"""读取侧契约状态测试：重复/孤儿/缺失契约的排除语义诊断）。"""
from __future__ import annotations

from pathlib import Path

import yaml

from hongzhao.contracts import contract_state_issues
from hongzhao.core import load_registry

BASE_CONFIG = (Path(__file__).resolve().parents[1] / "fixtures" / "containment" / "config_base.yaml").read_text(encoding="utf-8")


def make_kit(tmp: Path) -> Path:
    kit = tmp / "memory"
    kit.mkdir(parents=True, exist_ok=True)
    (kit / "config.yaml").write_text(BASE_CONFIG, encoding="utf-8")
    (kit / "raw").mkdir(exist_ok=True)
    (kit / "registry").mkdir(exist_ok=True)
    (kit / "registry" / "project-registry.yaml").write_text("schema_version: 2\nprojects: []\n", encoding="utf-8")
    (kit / "registry" / "knowledge-registry.yaml").write_text("schema_version: 2\nknowledge: []\n", encoding="utf-8")
    return kit


def write_contract(directory: Path, project_id: str, project_key: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "project-view.md").write_text(
        f"---\nschema_version: 2\nproject_id: {project_id}\nproject_key: {project_key}\n"
        "project_name: n\npurpose: p\ncurrent_state: c\nnext_action: n\n"
        "status: active\nactivation: on-demand\nentrypoints: []\nupdated_at: 2026-10-29\n---\nbody\n",
        encoding="utf-8",
    )


def set_entries(kit: Path, entries: list[dict]) -> None:
    (kit / "registry" / "project-registry.yaml").write_text(
        yaml.safe_dump({"schema_version": 2, "projects": entries}, sort_keys=False), encoding="utf-8"
    )


def codes(kit: Path) -> set[str]:
    registry, _ = load_registry(kit)
    return {c for c, _m, _p in contract_state_issues(kit, registry)}


ID1 = "proj-11111111-1111-4111-8111-111111111111"
ID2 = "proj-22222222-2222-4222-8222-222222222222"


def test_orphan_central_reported(tmp_path):
    kit = make_kit(tmp_path)
    write_contract(kit / "projects" / "alpha", ID1, "alpha")
    assert "CONTRACT_ORPHAN" in codes(kit)


def test_key_mismatch_reported(tmp_path):
    kit = make_kit(tmp_path)
    write_contract(kit / "projects" / "beta", ID1, "alpha")  # 目录名≠frontmatter key
    assert "CONTRACT_KEY_MISMATCH" in codes(kit)


def test_missing_contract_reported(tmp_path):
    kit = make_kit(tmp_path)
    set_entries(kit, [{"project_id": ID1, "location": {"kind": "external", "path": str(tmp_path / "gone")},
                       "registered_at": "2026-10-01", "last_checked_at": "2026-10-01"}])
    assert "CONTRACT_MISSING" in codes(kit)


def test_same_key_two_ids_reported(tmp_path):
    kit = make_kit(tmp_path)
    write_contract(kit / "projects" / "alpha", ID1, "alpha")
    write_contract(kit / "projects" / "beta", ID2, "alpha")
    assert "CONTRACT_KEY_DUPLICATE" in codes(kit)


def test_clean_state_no_issues(tmp_path):
    kit = make_kit(tmp_path)
    proj = tmp_path / "proj"
    write_contract(proj, ID1, "alpha")
    set_entries(kit, [{"project_id": ID1, "location": {"kind": "external", "path": str(proj)},
                       "registered_at": "2026-10-01", "last_checked_at": "2026-10-01"}])
    assert codes(kit) == set()
