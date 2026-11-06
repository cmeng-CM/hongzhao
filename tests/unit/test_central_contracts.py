"""J6 中央契约回归（ 后续）：register 建中央契约后 compile 不得 CONTRACT_MISSING。

此前缺陷：load_contracts 只查项目根契约，J6（无根契约→新建中央契约）注册成功后
compile/validate 立即 degraded。修复=中央契约回退（与 doctor 的 contract_state_issues
口径一致）。同时覆盖：J1 双形态（根契约优先）、项目视图路由（project scope 记忆
落 projects/<key>.md）。
"""
from __future__ import annotations

from pathlib import Path

from hongzhao.render import compile_all

FIX = Path(__file__).resolve().parents[1] / "fixtures"
BASE = (FIX / "containment" / "config_base.yaml").read_text(encoding="utf-8")

PROJ_MEM = """---
schema_version: 2
id: mem-1234aaaa-0000-4000-8000-000000000001
created: 2026-11-02
source: user
topic: j6
kind: memory
scope: project
project_id: proj-2222bbbb-1111-4222-8333-444455556666
activation: on-demand
record_type: source
summary: Project-scoped fact for the central contract.
compile_status: done
---

Body.
"""


def make_kit(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.yaml").write_text(BASE, encoding="utf-8")
    (base / "raw").mkdir(exist_ok=True)
    (base / "registry").mkdir(exist_ok=True)
    (base / "registry" / "project-registry.yaml").write_text("schema_version: 2\nprojects: []\n", encoding="utf-8")
    (base / "registry" / "knowledge-registry.yaml").write_text("schema_version: 2\nknowledge: []\n", encoding="utf-8")
    return base


def _register_j6(kit: Path, proj_root: Path) -> None:
    """模拟 cmd_register J6 终态：registry 条目 + 中央契约（无项目根契约）。"""
    (kit / "registry" / "project-registry.yaml").write_text(
        "schema_version: 2\n"
        "projects:\n"
        "  - project_id: proj-2222bbbb-1111-4222-8333-444455556666\n"
        "    location: {kind: external, path: " + str(proj_root) + "}\n"
        "    registered_at: '2026-11-02'\n"
        "    last_checked_at: '2026-11-02'\n",
        encoding="utf-8",
    )
    central = kit / "projects" / "j6key"
    central.mkdir(parents=True)
    (central / "project-view.md").write_text(
        "---\n"
        "schema_version: 2\n"
        "project_id: proj-2222bbbb-1111-4222-8333-444455556666\n"
        "project_key: j6key\n"
        "project_name: J6 Demo\n"
        "updated_at: '2026-11-02'\n"
        "status: active\n"
        "purpose: p\n"
        "current_state: s\n"
        "next_action: n\n"
        "activation: on-demand\n"
        "entrypoints: []\n"
        "---\n\n<!-- PROJECT_VIEW_GENERATED:START -->\n概况\n<!-- PROJECT_VIEW_GENERATED:END -->\n\n## 关键决策\n\n## 问题、卡点与风险\n",
        encoding="utf-8",
    )


def test_j6_central_contract_then_compile_is_clean(tmp_path):
    kit = make_kit(tmp_path / "kit")
    proj_root = tmp_path / "proj"
    proj_root.mkdir()
    _register_j6(kit, proj_root)
    (kit / "raw" / "proj-mem.md").write_text(PROJ_MEM, encoding="utf-8")

    code, issues = compile_all(kit)
    assert code == 0, [i.format() for i in issues]
    assert not [i for i in issues if i.code == "CONTRACT_MISSING"]
    # project scope 记忆路由到以 project_key 命名的视图
    view = kit / "compiled" / "effective-memory" / "projects" / "j6key.md"
    assert view.is_file()
    assert "Project-scoped fact" in view.read_text(encoding="utf-8")


def test_root_and_central_coexisting_flags_duplicate_but_root_wins(tmp_path):
    # rc6 三命令口径统一：根契约+中央契约并存 → CONTRACT_DUPLICATE（degraded），
    # 但解析仍按根契约（project_key=j6root 的视图生成可证）。
    kit = make_kit(tmp_path / "kit")
    proj_root = tmp_path / "proj"
    proj_root.mkdir()
    _register_j6(kit, proj_root)  # 中央契约（key=j6key）
    root_contract = proj_root / "project-view.md"
    root_contract.write_text(
        (kit / "projects" / "j6key" / "project-view.md").read_text(encoding="utf-8").replace(
            "project_key: j6key", "project_key: j6root"
        ),
        encoding="utf-8",
    )
    (kit / "raw" / "proj-mem.md").write_text(PROJ_MEM, encoding="utf-8")
    code, issues = compile_all(kit)
    assert code == 1
    assert [i for i in issues if i.code == "CONTRACT_DUPLICATE"]
    assert not [i for i in issues if i.code == "CONTRACT_MISSING"]
    # 根契约仍生效：视图按根契约 key 命名
    assert (kit / "compiled" / "effective-memory" / "projects" / "j6root.md").is_file()
    assert "Project-scoped fact" in (kit / "compiled" / "effective-memory" / "projects" / "j6root.md").read_text(encoding="utf-8")


def test_missing_both_forms_still_reports(tmp_path):
    # 既无根契约也无中央契约：CONTRACT_MISSING 照报（不掩盖真缺失）
    kit = make_kit(tmp_path / "kit")
    proj_root = tmp_path / "proj"
    proj_root.mkdir()
    (kit / "registry" / "project-registry.yaml").write_text(
        "schema_version: 2\n"
        "projects:\n"
        "  - project_id: proj-3333cccc-1111-4222-8333-444455556666\n"
        "    location: {kind: external, path: " + str(proj_root) + "}\n",
        encoding="utf-8",
    )
    code, issues = compile_all(kit)
    assert code == 1
    assert [i for i in issues if i.code == "CONTRACT_MISSING"]
