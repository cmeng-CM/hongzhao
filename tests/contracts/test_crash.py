# -*- coding: utf-8 -*-
# 修改记录（RB-02 转绿期 harness 修正）：2026-10-29，修改人=t16-author；差异：_register 参数组装 list(extra)+FIELDS → FIELDS+list(extra)（argparse 重复旗标后者生效，extra 应生效）；理由=harness 参数序缺陷（非断言问题；断言与其余用例零改动）。
""" 崩溃与重试、 写序列失败恢复（合同测试：真实入口 +  故障注入）。

故障注入双条件：HONGZHAO_TEST=1 且 HONGZHAO_FAULT=<point>。
本文件覆盖 4 个注入点中的 3 个：after-registry-write、mid-contract-write、
contract-write；after-registry-delete 在 test_unregister.py（⑦）。
②（写失败后契约逐字节不变、锁已释放）按 design  只能靠 hook 验证。
"""

from pathlib import Path

from conftest import (
    FAULT_AFTER_REGISTRY_WRITE,
    FAULT_CONTRACT_WRITE,
    FAULT_MID_CONTRACT_WRITE,
    add_registry_entry,
    fault_env,
    find_centrals,
    make_memory_root,
    out_of,
    read_contract,
    registry_entries,
    run_cli,
    snapshot_state,
    write_contract,
)

# 无关孤儿契约 id（①「不误认领他人 orphan」用）
ID_W = "proj-55555555-5555-4555-8555-555555555555"

FIELDS = ["--purpose", "Purpose for crash test",
          "--current-state", "Active state under test",
          "--next-action", "Next action under test"]


def _proj(tmp_path, name="alpha"):
    directory = tmp_path / "work" / name
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _register(proj, root, extra=None, fault=None):
    args = ["project-register", str(Path(proj).resolve())] + FIELDS + list(extra or [])
    return run_cli(args, root, env_extra=fault_env(fault) if fault else None)


def test_a11_1_crash_after_registry_write_retry_hits_j3(tmp_path):
    """①：J6 注入 after-registry-write 崩溃 → 重试（不带 --key）命中 J3。

    断言：契约补建、project_id 与 registry 条目相同、registry 仍只一条、
    不新建第二份契约、不误认领他人 orphan。
    """
    root = make_memory_root(tmp_path)
    proj = _proj(tmp_path)
    # 他人 orphan：central 存在、registry 无条目；重试不得认领它
    unrelated = write_contract(root / "projects" / "unrelated",
                               project_id=ID_W, project_key="unrelated")
    unrelated_before = unrelated.read_bytes()

    res = _register(proj, root, fault=FAULT_AFTER_REGISTRY_WRITE)
    assert res.returncode != 0, "fault injection must crash the process (non-zero exit)"
    entries = registry_entries(root)
    assert len(entries) == 1, "crash state: registry written, contract not yet"

    retry = _register(proj, root)  # 不带 --key（原 key 即目录名 slug=alpha）
    assert retry.returncode == 0, f"retry must hit J3 and rebuild; output: {out_of(retry)}"

    entries = registry_entries(root)
    assert len(entries) == 1, "registry must keep exactly one entry after retry"
    central = root / "projects" / "alpha" / "project-view.md"
    assert central.is_file(), "central contract must be rebuilt"
    fm = read_contract(central)
    assert fm["project_id"] == entries[0]["project_id"], (
        "rebuilt contract id must equal the registry entry id (no new id)"
    )
    assert len(find_centrals(root)) == 2, "exactly our new central plus the untouched orphan"
    assert unrelated.read_bytes() == unrelated_before, "foreign orphan must not be touched"
    assert all(read_contract(c)["project_id"] != ID_W or c == unrelated for c in find_centrals(root)), (
        "retry must not adopt the foreign orphan"
    )
    ids = [e["project_id"] for e in registry_entries(root)]
    assert ID_W not in ids, "retry must not add a registry entry for the foreign orphan"


def test_a11_2_manual_central_delete_retry_hits_j3(tmp_path):
    """②：已登记路径手工删除 central 契约后重试 → 命中 J3，语义同①。"""
    root = make_memory_root(tmp_path)
    proj = _proj(tmp_path)

    first = _register(proj, root)
    assert first.returncode == 0, f"initial J6 registration must succeed; output: {out_of(first)}"
    central = root / "projects" / "alpha" / "project-view.md"
    assert central.is_file()
    original_id = read_contract(central)["project_id"]

    # 手工删除 central 契约（模拟崩溃后/误删的中间态）
    central.unlink()

    retry = _register(proj, root)
    assert retry.returncode == 0, f"retry must hit J3 and rebuild; output: {out_of(retry)}"
    assert central.is_file(), "central contract must be rebuilt"
    fm = read_contract(central)
    entries = registry_entries(root)
    assert fm["project_id"] == original_id, "rebuilt contract must reuse the original id"
    assert len(entries) == 1, "registry must keep exactly one entry"
    assert entries[0]["project_id"] == original_id, "registry id must be unchanged"
    assert len(find_centrals(root)) == 1, "no second contract may appear"


def test_a11_3_nonascii_dir_retry_without_key_field_invalid(tmp_path):
    """③：非 ASCII 目录名 + 崩溃后不带 --key 重试 → FIELD_INVALID 并提示传 --key（R6 M6）。"""
    root = make_memory_root(tmp_path)
    # 非 ASCII 目录名：slug 无法推导 K
    proj = _proj(tmp_path, "项目甲")

    # 首次注册显式传 --key 才能落 registry，随后崩溃（registry 已写、契约未写）
    res = _register(proj, root, extra=["--key", "cjk-proj"], fault=FAULT_AFTER_REGISTRY_WRITE)
    assert res.returncode != 0, "fault injection must crash the process"
    assert len(registry_entries(root)) == 1

    # 重试不带 --key：K 算不出来 → FIELD_INVALID（零写入）
    before = snapshot_state(root, [proj])
    retry = _register(proj, root)
    output = out_of(retry)
    assert retry.returncode != 0, "retry without --key must fail with FIELD_INVALID"
    assert "FIELD_INVALID" in output, f"expected FIELD_INVALID in output; got: {output}"
    assert "--key" in output, f"output must hint passing --key; got: {output}"
    assert snapshot_state(root, [proj]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )
    assert len(find_centrals(root)) == 0, "no contract may be created"


def test_a11_4_mid_contract_write_takeover_residual_dir(tmp_path):
    """④：mid-contract-write（mkdir 后、replace 前崩溃）→ 重试命中 J3 接管残留目录、无残留（R7 P1）。"""
    root = make_memory_root(tmp_path)
    proj = _proj(tmp_path)

    res = _register(proj, root, fault=FAULT_MID_CONTRACT_WRITE)
    assert res.returncode != 0, "fault injection must crash the process"
    # 场景前提：磁盘上留下 projects/<K>/（空目录或仅临时文件）
    assert (root / "projects" / "alpha").is_dir(), (
        "mid-contract-write crash must leave the projects/<K>/ directory (R7 P1 premise)"
    )

    retry = _register(proj, root)
    assert retry.returncode == 0, f"retry must take over the residual directory; output: {out_of(retry)}"
    central = root / "projects" / "alpha" / "project-view.md"
    assert central.is_file(), "central contract must be rebuilt"
    entries = registry_entries(root)
    assert len(entries) == 1
    assert read_contract(central)["project_id"] == entries[0]["project_id"]
    # 无残留：不得留下 .project-view.md.* 临时文件
    leftovers = [p for p in (root / "projects").rglob(".project-view.md.*")]
    assert leftovers == [], f"no temp-file residue expected, found: {leftovers}"
    assert len(find_centrals(root)) == 1, "no second contract may appear"


def test_a12_1_j6_contract_write_failure_rolls_back(tmp_path):
    """①：J6 新建时契约写失败（contract-write）→ registry 条目删除、目录无残留、exit 2、锁释放。"""
    root = make_memory_root(tmp_path)
    proj = _proj(tmp_path)

    res = _register(proj, root, fault=FAULT_CONTRACT_WRITE)
    assert res.returncode == 2, f"J6 contract-write failure must exit 2; got rc={res.returncode}; output: {out_of(res)}"
    # 刚加的 registry 条目被删除
    assert registry_entries(root) == [], "the just-added registry entry must be rolled back"
    # projects/<K>/ 不留空目录或临时文件；零契约
    key_dir = root / "projects" / "alpha"
    assert not key_dir.exists() or not any(key_dir.iterdir()), (
        "no empty directory or temp-file residue may survive the rollback"
    )
    assert find_centrals(root) == [], "no central contract may exist"

    # 锁均已释放：随后 register 可立即执行
    retry = _register(proj, root)
    assert retry.returncode == 0, f"lock must be released so retry succeeds; output: {out_of(retry)}"
    assert (root / "projects" / "alpha" / "project-view.md").is_file()


def test_a12_2_j2_contract_write_failure_atomic(tmp_path):
    """②：J2 更新时契约写失败（contract-write）→ 契约逐字节不变、registry 仅 last_checked_at 变化、锁释放。

    按 design ：该状态（原子替换未发生）只能靠 hook 验证，无法用外部构造覆盖。
    """
    root = make_memory_root(tmp_path)
    proj = _proj(tmp_path)
    add_registry_entry(root, "proj-22222222-2222-4222-8222-222222222222", proj)
    central = write_contract(root / "projects" / "alpha",
                             project_id="proj-22222222-2222-4222-8222-222222222222",
                             project_key="alpha", purpose="Original purpose")
    central_before = central.read_bytes()
    entry_before = dict(registry_entries(root)[0])

    res = _register(proj, root, extra=["--purpose", "Should never be applied"],
                    fault=FAULT_CONTRACT_WRITE)
    assert res.returncode != 0, "injected contract-write failure must not report success"

    # 契约逐字节不变（原子替换未发生）
    assert central.read_bytes() == central_before, (
        "central contract must stay byte-identical when its write fails (atomic replace not reached)"
    )
    # registry 仅 last_checked_at 变化：其余字段逐项相等
    entries = registry_entries(root)
    assert len(entries) == 1, "registry entry must survive"
    strip = lambda e: {k: v for k, v in e.items() if k != "last_checked_at"}
    assert strip(entries[0]) == strip(entry_before), (
        "registry may only differ in last_checked_at"
    )

    # 锁均已释放：随后 register 可立即执行且更新生效
    retry = _register(proj, root, extra=["--purpose", "Applied after retry"])
    assert retry.returncode == 0, f"lock must be released so retry succeeds; output: {out_of(retry)}"
    assert read_contract(central)["purpose"] == "Applied after retry"
