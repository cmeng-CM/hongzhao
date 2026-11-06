# -*- coding: utf-8 -*-
""" 合同测试：project-unregister 全边界（7 例，真实 CLI 入口）。

依据 design  「注销」：dry-run 默认、--yes 执行；默认删 registry 条目 + central
契约；项目根契约永不删除；--keep-contract 保留 central；--delete-project-contract
只删项目根；两删除旗标互斥；写序先删 registry、再删 central。
⑦ 使用故障注入点 after-registry-delete。
"""

from pathlib import Path

from conftest import (
    FAULT_AFTER_REGISTRY_DELETE,
    add_registry_entry,
    fault_env,
    find_centrals,
    make_memory_root,
    out_of,
    registry_entries,
    run_cli,
    snapshot_state,
    write_contract,
)

FIELDS = ["--purpose", "Purpose for unregister test",
          "--current-state", "Active state under test",
          "--next-action", "Next action under test"]


def _proj(tmp_path, rel="work/alpha"):
    directory = tmp_path / rel
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _unregister(target, root, extra=None, fault=None):
    args = ["project-unregister", str(target)] + list(extra or [])
    return run_cli(args, root, env_extra=fault_env(fault) if fault else None)


def _j6_state(tmp_path):
    """构造「已注册 central」状态：经真实 CLI 走一次 J6 新建。"""
    root = make_memory_root(tmp_path)
    proj = _proj(tmp_path)
    res = run_cli(["project-register", str(proj.resolve())] + FIELDS, root)
    assert res.returncode == 0, f"J6 setup registration failed; output: {out_of(res)}"
    assert registry_entries(root) and find_centrals(root), "setup must produce entry+central"
    return root, proj


def test_a13_1_default_deletes_registry_and_central(tmp_path):
    """①：默认（--yes）删 registry + central；此前 dry-run 默认零写入。"""
    root, proj = _j6_state(tmp_path)
    central = root / "projects" / "alpha" / "project-view.md"

    # dry-run 默认：只打印计划，零写入
    before = snapshot_state(root, [proj])
    dry = _unregister(proj, root)
    assert dry.returncode == 0, f"dry-run must succeed; output: {out_of(dry)}"
    assert snapshot_state(root, [proj]) == before, "dry-run must not modify anything"

    res = _unregister(proj, root, extra=["--yes"])
    assert res.returncode == 0, f"unregister --yes must succeed; output: {out_of(res)}"
    assert registry_entries(root) == [], "registry entry must be deleted"
    assert not central.exists(), "central contract must be deleted"


def test_a13_2_keep_contract_leaves_orphan(tmp_path):
    """②：--keep-contract 保留 central + 提示 CONTRACT_ORPHAN 与清理路径。"""
    root, proj = _j6_state(tmp_path)
    central = root / "projects" / "alpha" / "project-view.md"
    central_before = central.read_bytes()

    res = _unregister(proj, root, extra=["--yes", "--keep-contract"])
    output = out_of(res)
    assert res.returncode == 0, f"unregister --keep-contract must succeed; output: {output}"
    assert registry_entries(root) == [], "registry entry must be deleted"
    assert central.is_file(), "central contract must be kept"
    assert central.read_bytes() == central_before, "kept central must stay byte-identical"
    assert "CONTRACT_ORPHAN" in output, "result must warn about the upcoming CONTRACT_ORPHAN"
    assert "alpha" in output, "result must point at the orphan (key/path)"


def test_a13_3_delete_project_contract_only(tmp_path):
    """③：--delete-project-contract 只删项目根、不动 central。

    构造「已注册_项目根」（J1-a 形态：registry + 项目根契约，无 central）。
    语义按 ③「只删项目根」+  语义：注销自身仍删 registry 条目，
    旗标额外授权删除项目根契约（默认永不删除）。
    """
    root = make_memory_root(tmp_path)
    proj = _proj(tmp_path)
    write_contract(proj, project_id="proj-11111111-1111-4111-8111-111111111111",
                   project_key="alpha")
    add_registry_entry(root, "proj-11111111-1111-4111-8111-111111111111", proj)

    res = _unregister(proj, root, extra=["--yes", "--delete-project-contract"])
    assert res.returncode == 0, f"unregister --delete-project-contract must succeed; output: {out_of(res)}"
    assert not (proj / "project-view.md").exists(), "project-root contract must be deleted"
    assert registry_entries(root) == [], "registry entry must be deleted"
    assert find_centrals(root) == [], "central must not be created or touched"


def test_a13_4_mutually_exclusive_flags_rejected(tmp_path):
    """④：--keep-contract 与 --delete-project-contract 同传 → INVALID_FLAG_COMBINATION（零写入）。"""
    root, proj = _j6_state(tmp_path)

    before = snapshot_state(root, [proj])
    res = _unregister(proj, root, extra=["--yes", "--keep-contract", "--delete-project-contract"])
    output = out_of(res)
    assert res.returncode != 0, "flag combination must be rejected"
    assert "INVALID_FLAG_COMBINATION" in output, (
        f"expected INVALID_FLAG_COMBINATION in output; got: {output}"
    )
    assert snapshot_state(root, [proj]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )


def test_a13_5_project_root_state_prints_residual_path(tmp_path):
    """⑤：注销「已注册_项目根」→ 删 registry 且打印项目根契约残留路径（契约保留）。"""
    root = make_memory_root(tmp_path)
    proj = _proj(tmp_path)
    write_contract(proj, project_id="proj-11111111-1111-4111-8111-111111111111",
                   project_key="alpha")
    add_registry_entry(root, "proj-11111111-1111-4111-8111-111111111111", proj)
    contract_before = (proj / "project-view.md").read_bytes()

    res = _unregister(proj, root, extra=["--yes"])
    output = out_of(res)
    assert res.returncode == 0, f"unregister must succeed; output: {output}"
    assert registry_entries(root) == [], "registry entry must be deleted"
    # 项目根契约永不删除（默认），且结果必须打印该残留路径
    assert (proj / "project-view.md").read_bytes() == contract_before, (
        "project-root contract must never be deleted by default unregister"
    )
    assert str((proj / "project-view.md").resolve()) in output, (
        f"result must print the residual project-root contract path; got: {output}"
    )


def test_a13_6_unregister_orphan_registry_side_only(tmp_path):
    """⑥：注销 orphan → 仅删 registry 语义并打印 orphan 路径。

    依据 ⑥「仅删 registry 并打印 orphan 路径」与  状态机边
    「orphan --unregister(仅删 registry)--> 终态_central残留」：orphan 本无 registry
    条目，registry 无变化，central 保留，结果打印 orphan 路径。
    （ 中「（删孤儿 central）」的括注与 ⑥/状态机存在文本张力，本测试按
    ⑥ + 状态机执行，已在 REPORT.md 记录，交 RB-02 复核。）
    """
    root = make_memory_root(tmp_path)
    write_contract(root / "projects" / "alpha",
                   project_id="proj-44444444-4444-4444-8444-444444444444",
                   project_key="alpha")
    orphan = root / "projects" / "alpha" / "project-view.md"
    orphan_before = orphan.read_bytes()

    before = snapshot_state(root)
    res = _unregister("alpha", root, extra=["--yes"])
    output = out_of(res)
    assert res.returncode == 0, f"unregister on an orphan must succeed; output: {output}"
    assert registry_entries(root) == [], "registry must stay empty (registry-side semantics only)"
    assert snapshot_state(root) == before, "registry and contracts must stay byte-identical"
    assert orphan.is_file() and orphan.read_bytes() == orphan_before, "central must remain"
    assert str(orphan.resolve()) in output, f"result must print the orphan path; got: {output}"


def test_a13_7_crash_after_registry_delete_leaves_orphan(tmp_path):
    """⑦：after-registry-delete 崩溃 → 留下 orphan（central 在、registry 无），doctor 报 CONTRACT_ORPHAN 并给清理命令。"""
    root, proj = _j6_state(tmp_path)
    central = root / "projects" / "alpha" / "project-view.md"
    central_before = central.read_bytes()

    res = _unregister(proj, root, extra=["--yes"], fault=FAULT_AFTER_REGISTRY_DELETE)
    assert res.returncode != 0, "fault injection must crash the process"
    assert registry_entries(root) == [], "registry entry deleted before the crash"
    assert central.is_file() and central.read_bytes() == central_before, (
        "central must survive the crash (orphan state)"
    )

    # doctor：degraded + CONTRACT_ORPHAN + 附带可执行清理命令
    doctor = run_cli(["doctor"], root)
    output = out_of(doctor)
    assert doctor.returncode == 1, f"CONTRACT_ORPHAN is degraded class, doctor must exit 1; got rc={doctor.returncode}"
    assert "CONTRACT_ORPHAN" in output, f"doctor must report CONTRACT_ORPHAN; got: {output}"
    assert "project-unregister" in output, f"doctor must attach a repair command; got: {output}"
