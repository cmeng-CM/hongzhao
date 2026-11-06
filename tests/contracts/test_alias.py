# -*- coding: utf-8 -*-
""" 合同测试：project-register 旧签名别名（，真实 CLI 入口）。

旧签名：``project-register <project_id> --kind {vault,external} --path <path>``
（首个位置参数匹配 ``proj-<UUID>`` 形态）。语义：registry-only upsert，不写、不改
任何契约文件；打印 deprecation 提示与新写法；同样执行  检查（R6 M1）。
"""

from conftest import (
    add_registry_entry,
    location_of,
    make_memory_root,
    out_of,
    registry_entries,
    run_cli,
    snapshot_state,
)

ID_X = "proj-11111111-1111-4111-8111-111111111111"
ID_I = "proj-22222222-2222-4222-8222-222222222222"


def test_a33_legacy_signature_registry_only_upsert(tmp_path):
    """：旧签名（中文 Skill 现形式）→ registry 条目与原引擎语义一致、零契约读写、deprecation 提示。"""
    root = make_memory_root(tmp_path)
    proj = root / "work" / "alpha"  # memory root 内 → vault + root 相对路径
    proj.mkdir(parents=True, exist_ok=True)

    res = run_cli(
        ["project-register", ID_X, "--kind", "vault", "--path", "work/alpha"],
        root,
    )
    output = out_of(res)
    assert res.returncode == 0, f"legacy alias upsert must succeed; output: {output}"

    # registry 条目与原引擎语义一致：vault → root 相对路径（原样）
    entries = registry_entries(root)
    assert len(entries) == 1, "exactly one registry entry expected"
    assert entries[0]["project_id"] == ID_X, "entry id must equal the positional project_id"
    kind, path = location_of(entries[0])
    assert kind == "vault", "old-signature vault kind must be preserved"
    assert path == "work/alpha", "root-relative path must be stored as given (legacy semantics)"

    # 零契约文件读写：不产生任何 project-view.md
    assert not list((root / "projects").rglob("project-view.md")), (
        "alias must not create or modify any central contract"
    )
    assert not (proj / "project-view.md").exists(), (
        "alias must not create or modify any project-root contract"
    )

    # 打印 deprecation 提示与新写法
    lowered = output.lower()
    assert "deprecat" in lowered, f"deprecation hint expected in output; got: {output}"
    assert "project-register" in output, f"new-signature hint must reference the command; got: {output}"


def test_alias_enforces_i1_conflict_zero_write(tmp_path):
    """/R6 M1：别名同样执行  检查——该路径已登记为另一 id → CONTRACT_DUPLICATE 零写入。"""
    root = make_memory_root(tmp_path)
    proj = root / "work" / "alpha"
    proj.mkdir(parents=True, exist_ok=True)
    # 该路径已登记为另一 id I
    add_registry_entry(root, ID_I, proj)

    before = snapshot_state(root, [proj])
    res = run_cli(
        ["project-register", ID_X, "--kind", "vault", "--path", "work/alpha"],
        root,
    )
    output = out_of(res)
    assert res.returncode != 0, "alias upsert must reject a path already registered to another id"
    assert "CONTRACT_DUPLICATE" in output, (
        f"expected CONTRACT_DUPLICATE in output; got: {output}"
    )
    assert snapshot_state(root, [proj]) == before, (
        "zero-write violated: registry and contracts must stay byte-identical"
    )
