# -*- coding: utf-8 -*-
""" 合同测试：现有数据不回归（对只读副本跑 validate + / 基线复核）。

副本路径由环境变量 ``HONGZHAO_PARITY_FIXTURE`` 注入；缺变量时 skip（副本由
 影子基建在  执行前准备）。该变量必须指向生产库的**只读副本**，
绝不能指向 vault 生产库本身（开发期零接触生产库）。
"""

import os
from pathlib import Path

import pytest

from conftest import location_of, out_of, read_contract, registry_entries, run_cli

REGISTRY_REL = "registry/project-registry.yaml"


@pytest.fixture(scope="module")
def parity_root():
    """只读副本根：仅接受 HONGZHAO_PARITY_FIXTURE 注入；未设置即 skip。"""
    value = os.environ.get("HONGZHAO_PARITY_FIXTURE")
    if not value:
        pytest.skip(
            "HONGZHAO_PARITY_FIXTURE is not set:  must run against a READ-ONLY COPY "
            "of the production memory library (prepare the copy first; never point this "
            "variable at the live vault, )"
        )
    root = Path(value)
    assert root.is_dir(), f"parity fixture root is not a directory: {root}"
    return root


def _entry_project_dir(root, entry):
    """按  语义解析条目 location 指向的项目根（vault 相对 / external 绝对）。"""
    _, path = location_of(entry)
    base = Path(path) if Path(path).is_absolute() else (Path(root) / path)
    return base.resolve()


def test_a25_validate_reports_no_field_too_long(parity_root):
    """①：对全量数据跑 validate → 零 FIELD_TOO_LONG（实测最大 224 < 300）。"""
    registry_file = parity_root / REGISTRY_REL
    before = registry_file.read_bytes() if registry_file.is_file() else b""

    res = run_cli(["validate"], parity_root)
    output = out_of(res)
    assert "FIELD_TOO_LONG" not in output, (
        f"existing data must not trip the 300-char field limit; output: {output}"
    )

    # validate 是只读命令：registry 逐字节不变
    after = registry_file.read_bytes() if registry_file.is_file() else b""
    assert after == before, "validate must not modify the registry (read-only command)"


def test_a25_invariants_i1_i2_hold(parity_root):
    """②：/ 基线复核——一条路径至多一个 id；一个 project_key 至多一个项目。"""
    entries = registry_entries(parity_root)

    # ：registry 中不允许两条 location 解析到同一路径
    resolved = [str(_entry_project_dir(parity_root, e)) for e in entries]
    assert len(resolved) == len(set(resolved)), (
        " violated: one path is mapped to multiple project ids"
    )

    # ：集 A（central）与集 B（已登记项目根）中同 key 必须同 id
    contracts = list((parity_root / "projects").rglob("project-view.md")) \
        if (parity_root / "projects").is_dir() else []
    for entry in entries:
        contract = _entry_project_dir(parity_root, entry) / "project-view.md"
        if contract.is_file():
            contracts.append(contract)

    key_to_id = {}
    for contract in contracts:
        frontmatter = read_contract(contract)
        key, project_id = frontmatter.get("project_key"), frontmatter.get("project_id")
        if key in key_to_id:
            assert key_to_id[key] == project_id, (
                f" violated: key '{key}' is used by multiple project ids "
                f"({key_to_id[key]} vs {project_id})"
            )
        key_to_id[key] = project_id
