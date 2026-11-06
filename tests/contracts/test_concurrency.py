# -*- coding: utf-8 -*-
""" 合同测试：并发注册不丢更新（8 真实进程、真实文件系统、真实 flock，）。

三态：
①同一路径 ×8 → 1 条 registry、1 份契约、同一 project_id（先到 J6 新建、后到 J2 更新）；
②8 个不同路径 → 8 条条目无丢失、无重复 id；
③同一记忆根但各进程设不同 $HONGZHAO_CACHE → 仍互斥（锁绑定记忆根，R6 M4）。
附带断言（design 「锁文件混入版本库」行）：锁文件 <root>/.hongzhao.lock 持久存在。
"""

from pathlib import Path

from conftest import (
    location_of,
    make_memory_root,
    popen_cli,
    read_contract,
    registry_entries,
)


def _register_cmd(proj):
    return [
        "project-register", str(Path(proj).resolve()),
        "--purpose", "Purpose for concurrency test",
        "--current-state", "Active state under test",
        "--next-action", "Next action under test",
    ]


def _run_parallel(cmds, root, envs=None):
    """并发启动全部真实 CLI 进程，等待结束并收集 (returncode, combined_output)。"""
    envs = list(envs) if envs is not None else [None] * len(cmds)
    assert len(envs) == len(cmds)
    procs = [popen_cli(cmd, root, env_extra=env_extra) for cmd, env_extra in zip(cmds, envs)]
    results = []
    for proc in procs:
        stdout, stderr = proc.communicate(timeout=180)
        results.append((proc.returncode, (stdout or "") + (stderr or "")))
    return results


def test_a34_1_same_path_single_id(tmp_path):
    """①：8 进程并发注册同一路径 → 恰 1 条 registry、1 份契约、同一 project_id。"""
    root = make_memory_root(tmp_path)
    proj = tmp_path / "work" / "alpha"
    proj.mkdir(parents=True, exist_ok=True)

    results = _run_parallel([_register_cmd(proj)] * 8, root)
    for rc, output in results:
        assert rc == 0, (
            f"concurrent same-path register must degrade to J6-then-J2 and succeed; output: {output}"
        )

    entries = registry_entries(root)
    assert len(entries) == 1, f"exactly one registry entry expected, got {len(entries)}"
    centrals = [p for p in (root / "projects").rglob("project-view.md")]
    assert len(centrals) == 1, f"exactly one central contract expected, got {len(centrals)}"
    assert read_contract(centrals[0])["project_id"] == entries[0]["project_id"], (
        "central id must equal the single registry id"
    )
    # 附带断言：锁文件绑定记忆根且持久存在风险表）
    assert (root / ".hongzhao.lock").exists(), "lock file <root>/.hongzhao.lock must exist"


def test_a34_2_eight_distinct_paths_no_loss(tmp_path):
    """②：8 进程并发注册 8 个不同路径 → 8 条条目无丢失、无重复 id。"""
    root = make_memory_root(tmp_path)
    names = [f"p{i}" for i in range(1, 9)]
    for name in names:
        (tmp_path / "work" / name).mkdir(parents=True, exist_ok=True)

    cmds = [_register_cmd(tmp_path / "work" / name) for name in names]
    results = _run_parallel(cmds, root)
    for rc, output in results:
        assert rc == 0, f"concurrent distinct-path register must succeed; output: {output}"

    entries = registry_entries(root)
    assert len(entries) == 8, f"no entry may be lost, expected 8, got {len(entries)}"
    ids = [e["project_id"] for e in entries]
    assert len(set(ids)) == 8, "no duplicate project ids allowed"

    # 每条目各有一份 central 契约，id 与 registry 一致
    for entry in entries:
        _, path = location_of(entry)
        key = Path(path).name  # central 目录名 = project_key = 目录名 slug
        central = root / "projects" / key / "project-view.md"
        assert central.is_file(), f"central contract missing for {key}"
        assert read_contract(central)["project_id"] == entry["project_id"], (
            f"central id mismatch for {key}"
        )


def test_a34_3_distinct_cache_env_still_exclusive(tmp_path):
    """③：同一记忆根、各进程不同 $HONGZHAO_CACHE → 仍互斥（锁绑定记忆根，R6 M4）。"""
    root = make_memory_root(tmp_path)
    proj = tmp_path / "work" / "alpha"
    proj.mkdir(parents=True, exist_ok=True)

    envs = [{"HONGZHAO_CACHE": f"cache-{i}"} for i in range(8)]
    results = _run_parallel([_register_cmd(proj)] * 8, root, envs=envs)
    for rc, output in results:
        assert rc == 0, (
            f"register must succeed regardless of HONGZHAO_CACHE; output: {output}"
        )

    entries = registry_entries(root)
    assert len(entries) == 1, (
        "lock is bound to the memory root, not to env state: exactly one entry expected"
    )
    centrals = [p for p in (root / "projects").rglob("project-view.md")]
    assert len(centrals) == 1, "exactly one central contract expected"
    assert read_contract(centrals[0])["project_id"] == entries[0]["project_id"], (
        "single id across all processes expected"
    )
