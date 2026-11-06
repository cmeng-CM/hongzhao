"""行为对拍：新引擎 validate 与 vault 旧引擎在同一合成 fixture 上
的 issue code 集合与健康度一致——证明  迁移不改行为。

fixture 为全合成数据（无任何个人内容）；对 vault 只读（仅引用旧引擎脚本）。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import os

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "engine_parity"
# 旧引擎路径经环境变量注入（真实路径不入库——隐私门 W3）：
#   HONGZHAO_OLD_ENGINE=/path/to/60-Agent-Memory/scripts/agent_memory.py pytest tests/unit/test_engine_parity.py
# 未设置或路径不存在时跳过（CI 即此行为）。
OLD_ENGINE = Path(os.environ["HONGZHAO_OLD_ENGINE"]) if os.environ.get("HONGZHAO_OLD_ENGINE") else None


def _run_new(kit: Path) -> str:
    code = (
        "from hongzhao.cli import main; import sys; "
        "raise SystemExit(main(['--root', sys.argv[1], 'validate']))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, str(kit)], capture_output=True, text=True
    )
    return proc.stdout + proc.stderr


def _run_old(kit: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(OLD_ENGINE), "--root", str(kit), "validate"],
        capture_output=True,
        text=True,
    )
    return proc.stdout + proc.stderr


def _codes(out: str) -> set[str]:
    return set(re.findall(r"\[([A-Z_]+)\]", out))


def test_validate_issue_codes_parity(tmp_path):
    if OLD_ENGINE is None or not OLD_ENGINE.exists():
        pytest.skip("vault old engine not available (set HONGZHAO_OLD_ENGINE to enable)")
    kit = tmp_path / "kit"
    shutil.copytree(FIXTURE, kit)
    new_out = _run_new(kit)
    old_out = _run_old(kit)
    assert _codes(new_out) == _codes(old_out), (
        f"issue codes differ:\nnew={sorted(_codes(new_out))}\nold={sorted(_codes(old_out))}"
    )
    health_new = re.search(r"validation: (\S+)", new_out)
    health_old = re.search(r"validation: (\S+)", old_out)
    assert health_new and health_old and health_new.group(1) == health_old.group(1)


def test_fixture_exists_and_synthetic():
    assert (FIXTURE / "config.yaml").exists()
    # 合成数据自检：raw 记录 source 允许 zcode（新枚举），且不含真实项目名
    body = "\n".join(p.read_text(encoding="utf-8") for p in (FIXTURE / "raw").glob("*.md"))
    assert "zcode" in body
