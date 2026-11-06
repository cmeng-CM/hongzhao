# -*- coding: utf-8 -*-
""" 合同测试：design  「状态 → 判定对照表」#1–#16 逐行（真实 CLI 入口）。

每例对应对照表一行（id=case_01…case_16，收集输出形如 test_state_matrix_row[case_NN]），
断言「结果」列：
- 失败行断言结果列中的英文错误码标识符 + 零写入（registry 与契约逐字节不变）；
- 成功行断言结构性结果（登记/更新/补建/认领/新建的落盘语义）。
结果列的中文说明（如「登记 registry（沿用 X）」）不进断言： 规定用户可见输出
全英文，中文只存在于设计文本中；断言落在错误码标识符与可观察的文件系统结果上。
行 #7/#8 的结果是双形态（「登记／KEY_CONFLICT」「更新 central（--key 不符 →
KEY_CONFLICT）」），用例内覆盖两种形态。
"""

from pathlib import Path

import pytest

from conftest import (
    add_registry_entry,
    find_centrals,
    location_of,
    make_memory_root,
    out_of,
    read_contract,
    registry_entries,
    run_cli,
    snapshot_state,
    write_contract,
)

# 固定身份（形态均为 proj-<UUID>，跨集比对一律经 project_id 中转）
ID_X = "proj-11111111-1111-4111-8111-111111111111"
ID_I = "proj-22222222-2222-4222-8222-222222222222"
ID_Y = "proj-33333333-3333-4333-8333-333333333333"
ID_Z = "proj-44444444-4444-4444-8444-444444444444"

# 三必填字段旗标（J3/J6 预判需要字段；J1/J2 不收集，本模块对 J3/J6 预判用例显式传入，
# 避免任何交互等待）
FIELDS = ["--purpose", "Purpose for contract test",
          "--current-state", "Active state under test",
          "--next-action", "Next action under test"]


def _register(path, root, extra=None, env_extra=None):
    """执行真实 CLI：project-register <路径> [旗标]。"""
    args = ["project-register", str(Path(path).resolve())] + list(extra or [])
    return run_cli(args, root, env_extra=env_extra)


def _must_fail_with(res, code):
    """失败路径通用断言：非零退出 + 输出含错误码标识符。"""
    output = out_of(res)
    assert res.returncode != 0, (
        f"expected failure with {code}, got rc=0; output: {output}"
    )
    assert code in output, (
        f"expected error code {code} in CLI output; got: {output}"
    )


def _proj_dir(tmp_path, rel="work/alpha"):
    directory = tmp_path / rel
    directory.mkdir(parents=True, exist_ok=True)
    return directory


# ---------------------------------------------------------------------------
# 状态对照表逐行（#1–#16）
# ---------------------------------------------------------------------------

def _row_01(tmp_path):
    """#1：R=无、C=X、A同id=无、A同key=无、B同key=无 → J1-a「登记 registry（沿用 X）」。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    contract = write_contract(proj, project_id=ID_X, project_key="alpha")
    contract_before = contract.read_bytes()

    res = _register(proj, root)
    assert res.returncode == 0, f"J1-a should register reusing X; output: {out_of(res)}"

    entries = registry_entries(root)
    assert len(entries) == 1, "exactly one registry entry expected (J1-a)"
    assert entries[0]["project_id"] == ID_X, "registry must reuse the contract's project_id X"
    _, path = location_of(entries[0])
    assert Path(path).resolve() == proj.resolve(), "entry location must resolve to the parameter path"

    # J1-a：契约文件不改写；不新建 central
    assert contract.read_bytes() == contract_before, "project-root contract must not be rewritten"
    assert find_centrals(root) == [], "no central contract may be created on J1-a"


def _row_02(tmp_path):
    """#2：B同key=有（id≠X）→ J1-n「CONTRACT_KEY_DUPLICATE」（零写入）。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    write_contract(proj, project_id=ID_X, project_key="alpha")
    # 另一已登记项目（集 B），契约 key 与 X.key 相同、id 不同
    other = _proj_dir(tmp_path, "other/alpha")
    write_contract(other, project_id=ID_Y, project_key="alpha")
    add_registry_entry(root, ID_Y, other)

    before = snapshot_state(root, [proj, other])
    res = _register(proj, root)
    _must_fail_with(res, "CONTRACT_KEY_DUPLICATE")
    assert snapshot_state(root, [proj, other]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )


def _row_03(tmp_path):
    """#3：A同key=有（id≠X）→ J1-c「CONTRACT_KEY_DUPLICATE」（零写入）。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    # 不传 --key：K=目录名 slug=alpha，与 X.key 一致（J1 行内 key 判定用 X.key）
    write_contract(proj, project_id=ID_X, project_key="alpha")
    # 集 A 中存在 key=X.key 的 central 契约（id≠X）
    write_contract(root / "projects" / "alpha", project_id=ID_Z, project_key="alpha")

    before = snapshot_state(root, [proj])
    res = _register(proj, root)
    _must_fail_with(res, "CONTRACT_KEY_DUPLICATE")
    assert snapshot_state(root, [proj]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )


def _row_04(tmp_path):
    """#4：A同id=有 X → J1-i「CONTRACT_DUPLICATE」（同 id 两处，零写入）。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    write_contract(proj, project_id=ID_X, project_key="alpha")
    # 集 A 已有 id=X 的 central 契约（在别的 key 目录下）
    write_contract(root / "projects" / "other", project_id=ID_X, project_key="other")

    before = snapshot_state(root, [proj])
    res = _register(proj, root)
    _must_fail_with(res, "CONTRACT_DUPLICATE")
    assert snapshot_state(root, [proj]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )


def _row_05(tmp_path):
    """#5：R=I（I≠X）→ J1-d「CONTRACT_DUPLICATE」（路径已被另一 id 登记；零写入、不新增第二个 id）。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    write_contract(proj, project_id=ID_X, project_key="alpha")
    # 该路径已登记为另一 id I
    add_registry_entry(root, ID_I, proj)

    before = snapshot_state(root, [proj])
    res = _register(proj, root)
    _must_fail_with(res, "CONTRACT_DUPLICATE")
    after = snapshot_state(root, [proj])
    assert after == before, (
        "zero-write violated: registry must stay byte-identical (no second id)"
    )


def _row_06(tmp_path):
    """#6：X 已登记在另一路径 → J1-d「CONTRACT_DUPLICATE」（复制目录形态，零写入）。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    write_contract(proj, project_id=ID_X, project_key="alpha")
    # 原项目：id=X 已登记在另一路径（本例形态=复制了项目目录）
    original = _proj_dir(tmp_path, "other/beta")
    write_contract(original, project_id=ID_X, project_key="alpha")
    add_registry_entry(root, ID_X, original)

    before = snapshot_state(root, [proj, original])
    res = _register(proj, root)
    _must_fail_with(res, "CONTRACT_DUPLICATE")
    assert snapshot_state(root, [proj, original]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )


def _row_07(tmp_path):
    """#7：R=I=X → 「登记／KEY_CONFLICT」（无 --key=J1-a 登记；--key≠X.key=J1-b KEY_CONFLICT）。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    contract = write_contract(proj, project_id=ID_X, project_key="alpha")
    add_registry_entry(root, ID_X, proj)
    contract_before = contract.read_bytes()

    # 形态一：无 --key → J1-a 登记（有条目刷新 last_checked_at，契约不改写）
    res = _register(proj, root)
    assert res.returncode == 0, f"J1-a should succeed for R=I=X; output: {out_of(res)}"
    entries = registry_entries(root)
    assert len(entries) == 1, "registry must keep exactly one entry"
    assert entries[0]["project_id"] == ID_X, "entry id must remain X"
    assert contract.read_bytes() == contract_before, "contract must not be rewritten (J1-a)"
    assert find_centrals(root) == [], "no central contract may be created on J1-a"

    # 形态二：传入 --key ≠ X.key → J1-b KEY_CONFLICT 零写入
    before = snapshot_state(root, [proj])
    res = _register(proj, root, extra=["--key", "beta"])
    _must_fail_with(res, "KEY_CONFLICT")
    assert snapshot_state(root, [proj]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )


def _row_08(tmp_path):
    """#8：R=I、C=无、A同id=有 I → J2「更新 central（--key 不符 → KEY_CONFLICT）」。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    add_registry_entry(root, ID_I, proj)
    write_contract(root / "projects" / "alpha", project_id=ID_I, project_key="alpha",
                   purpose="Original purpose")

    # 形态一：更新 central（显式字段生效、其余保留、id 不变）
    res = _register(proj, root, extra=["--purpose", "Updated purpose for J2"])
    assert res.returncode == 0, f"J2 should update the central contract; output: {out_of(res)}"
    entries = registry_entries(root)
    assert len(entries) == 1 and entries[0]["project_id"] == ID_I, "entry must remain (id=I)"
    fm = read_contract(root / "projects" / "alpha" / "project-view.md")
    assert fm["project_id"] == ID_I, "central id must remain I"
    assert fm["purpose"] == "Updated purpose for J2", "explicitly passed field must be applied"
    assert not (proj / "project-view.md").exists(), "J2 must not create a project-root contract"

    # 形态二：传入 --key ≠ central 的 key → 零写入 KEY_CONFLICT（R6 M7①）
    before = snapshot_state(root, [proj])
    res = _register(proj, root, extra=["--key", "beta"])
    _must_fail_with(res, "KEY_CONFLICT")
    assert snapshot_state(root, [proj]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )


def _row_09(tmp_path):
    """#9：R=I、C=无、A同id=无 I、A同key=有（其 id≠I）→ J3「KEY_CONFLICT」（零写入）。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    add_registry_entry(root, ID_I, proj)
    # projects/<K>/project-view.md 已存在（K=alpha=目录名 slug）且其 id≠I
    write_contract(root / "projects" / "alpha", project_id=ID_Z, project_key="alpha")

    before = snapshot_state(root, [proj])
    res = _register(proj, root, extra=FIELDS)
    _must_fail_with(res, "KEY_CONFLICT")
    assert snapshot_state(root, [proj]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )


def _row_10(tmp_path):
    """#10：R=I、C=无、A同key=无、B同key=有（id≠I）→ J3「KEY_CONFLICT」（R6 M2，零写入）。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    add_registry_entry(root, ID_I, proj)
    # 集 B 已用 K（另一已登记项目契约 key=alpha、id≠I）
    other = _proj_dir(tmp_path, "other/alpha")
    write_contract(other, project_id=ID_Y, project_key="alpha")
    add_registry_entry(root, ID_Y, other)

    before = snapshot_state(root, [proj, other])
    res = _register(proj, root, extra=FIELDS)
    _must_fail_with(res, "KEY_CONFLICT")
    assert snapshot_state(root, [proj, other]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )


def _row_11(tmp_path):
    """#11：R=I、C=无、A同id=无、A同key=无、B同key=无 → J3「补建 central（沿用 I）」。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    add_registry_entry(root, ID_I, proj)

    extra = ["--purpose", "Rebuilt purpose for J3"] + FIELDS[2:]
    res = _register(proj, root, extra=extra)
    assert res.returncode == 0, f"J3 should rebuild the central contract; output: {out_of(res)}"

    central = root / "projects" / "alpha" / "project-view.md"
    assert central.is_file(), "central contract must be rebuilt at projects/<K>/"
    fm = read_contract(central)
    assert fm["project_id"] == ID_I, "rebuilt central must reuse the registry id I"
    assert fm["purpose"] == "Rebuilt purpose for J3", "passed fields must be written"
    entries = registry_entries(root)
    assert len(entries) == 1, "registry must keep exactly one entry"
    assert entries[0]["project_id"] == ID_I, "registry id must remain I"
    assert len(find_centrals(root)) == 1, "no second contract may appear"
    assert not (proj / "project-view.md").exists(), "rebuild lands in central, not the project root"


def _row_12(tmp_path):
    """#12：R=无、C=无、A同key=有 K（id 未登记）、B同key=无 → J4「认领（--key+--yes）」。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    # orphan central：id 未登记在 registry
    orphan = write_contract(root / "projects" / "alpha", project_id=ID_Z, project_key="alpha")
    orphan_before = orphan.read_bytes()

    res = _register(proj, root, extra=["--key", "alpha", "--yes"])
    assert res.returncode == 0, f"J4 claim with --key and --yes must succeed; output: {out_of(res)}"

    entries = registry_entries(root)
    assert len(entries) == 1, "claim must add exactly one registry entry"
    assert entries[0]["project_id"] == ID_Z, "claim must reuse the orphan central's id"
    _, path = location_of(entries[0])
    assert Path(path).resolve() == proj.resolve(), "entry location must resolve to the parameter path"
    assert orphan.read_bytes() == orphan_before, "J4 rewrites registry only; central stays untouched"
    assert not (proj / "project-view.md").exists(), "claim must not create a project-root contract"


def _row_13(tmp_path):
    """#13：#12 + B同key=有（id≠central）→ J4「KEY_CONFLICT」（零写入）。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    write_contract(root / "projects" / "alpha", project_id=ID_Z, project_key="alpha")
    other = _proj_dir(tmp_path, "other/alpha")
    write_contract(other, project_id=ID_Y, project_key="alpha")
    add_registry_entry(root, ID_Y, other)

    before = snapshot_state(root, [proj, other])
    res = _register(proj, root, extra=["--key", "alpha", "--yes"])
    _must_fail_with(res, "KEY_CONFLICT")
    assert snapshot_state(root, [proj, other]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )


def _row_14(tmp_path):
    """#14：A同key=有 K（id 已登记在别处）→ J5「KEY_CONFLICT」（零写入并输出占用者）。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    # central 的 id 已登记在别的路径
    write_contract(root / "projects" / "alpha", project_id=ID_Z, project_key="alpha")
    original = _proj_dir(tmp_path, "other/beta")
    write_contract(original, project_id=ID_Z, project_key="beta")
    add_registry_entry(root, ID_Z, original)

    before = snapshot_state(root, [proj, original])
    res = _register(proj, root, extra=["--key", "alpha", "--yes"])
    _must_fail_with(res, "KEY_CONFLICT")
    assert snapshot_state(root, [proj, original]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )
    # 「输出占用者」：具体输出形态设计未定，仅要求失败不静默；不做文本级断言


def _row_15(tmp_path):
    """#15：R=无、C=无、A同key=无、B同key=有 → J6「KEY_CONFLICT」（R6 M2，零写入）。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)
    other = _proj_dir(tmp_path, "other/alpha")
    write_contract(other, project_id=ID_Y, project_key="alpha")
    add_registry_entry(root, ID_Y, other)

    before = snapshot_state(root, [proj, other])
    res = _register(proj, root, extra=FIELDS)
    _must_fail_with(res, "KEY_CONFLICT")
    assert snapshot_state(root, [proj, other]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )


def _row_16(tmp_path):
    """#16：R=无、C=无、A同key=无、B同key=无 → J6「新建（registry → 契约）」。"""
    root = make_memory_root(tmp_path)
    proj = _proj_dir(tmp_path)

    extra = ["--purpose", "Brand new purpose for J6"] + FIELDS[2:]
    res = _register(proj, root, extra=extra)
    assert res.returncode == 0, f"J6 should create registry then contract; output: {out_of(res)}"

    entries = registry_entries(root)
    assert len(entries) == 1, "exactly one registry entry expected (J6)"
    project_id = entries[0]["project_id"]
    assert str(project_id).startswith("proj-"), "generated id must have proj-<UUID> form"
    kind, path = location_of(entries[0])
    #  ②：项目根在 memory root 外 → external + 绝对路径
    assert kind == "external", "project outside memory root must be registered as external"
    assert Path(path).is_absolute(), "external location must be an absolute path"
    assert Path(path).resolve() == proj.resolve(), "entry location must resolve to the parameter path"

    central = root / "projects" / "alpha" / "project-view.md"
    assert central.is_file(), "central contract must be created at projects/<K>/"
    fm = read_contract(central)
    assert fm["project_id"] == project_id, "central id must match the registry entry"
    assert fm["project_key"] == "alpha", "central directory name equals the project key"
    assert fm["purpose"] == "Brand new purpose for J6", "passed fields must be written"
    assert not (proj / "project-view.md").exists(), "J6 writes central only, not the project root"


ROW_HANDLERS = {
    1: _row_01,
    2: _row_02,
    3: _row_03,
    4: _row_04,
    5: _row_05,
    6: _row_06,
    7: _row_07,
    8: _row_08,
    9: _row_09,
    10: _row_10,
    11: _row_11,
    12: _row_12,
    13: _row_13,
    14: _row_14,
    15: _row_15,
    16: _row_16,
}


@pytest.mark.parametrize("row", [
    pytest.param(1, id="case_01"),
    pytest.param(2, id="case_02"),
    pytest.param(3, id="case_03"),
    pytest.param(4, id="case_04"),
    pytest.param(5, id="case_05"),
    pytest.param(6, id="case_06"),
    pytest.param(7, id="case_07"),
    pytest.param(8, id="case_08"),
    pytest.param(9, id="case_09"),
    pytest.param(10, id="case_10"),
    pytest.param(11, id="case_11"),
    pytest.param(12, id="case_12"),
    pytest.param(13, id="case_13"),
    pytest.param(14, id="case_14"),
    pytest.param(15, id="case_15"),
    pytest.param(16, id="case_16"),
])
def test_state_matrix_row(row, tmp_path):
    """逐行执行 design  状态对照表第 row 行（，真实 CLI、真实文件系统）。"""
    ROW_HANDLERS[row](tmp_path)
