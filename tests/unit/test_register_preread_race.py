"""注册预判撕裂读回归：锁外预判抛 KEY_CONFLICT-orphan 时，命令以锁内权威判定为准。

复现方式：monkeypatch judge——首次调用（预判）抛 ContractError(KEY_CONFLICT orphan)，
第二次（锁内）返回 J2；修复前命令直接失败，修复后按 J2 更新成功。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from hongzhao import contracts
from hongzhao.contracts import ContractError, Judgment, cmd_register

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


def test_preread_error_defers_to_locked_judgment(tmp_path, monkeypatch):
    kit = _make_kit(tmp_path / "kit")
    proj = tmp_path / "alpha"
    proj.mkdir()
    real_judge = contracts.judge
    calls = {"n": 0}

    def torn_judge(root, param, key_flag=None):
        calls["n"] += 1
        if calls["n"] == 1:
            # 预判：读到「有中央契约、无注册条目」的瞬时孤儿态（撕裂读产物）
            raise ContractError("KEY_CONFLICT", "an orphan central exists at key 'alpha'")
        # 锁内：权威判定为 J6（全新注册，字段齐全 → 成功）
        return real_judge(root, param, key_flag)

    monkeypatch.setattr(contracts, "judge", torn_judge)
    args = {"purpose": "p", "current_state": "s", "next_action": "n"}
    assert cmd_register(kit, str(proj), args) == 0  # 修复前：预判异常直接冒出 → 失败
    entries = yaml.safe_load((kit / "registry" / "project-registry.yaml").read_text(encoding="utf-8"))
    assert len(entries["projects"]) == 1
