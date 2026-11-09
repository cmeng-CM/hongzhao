# 修改记录（W1/E2b，2026-11-09）：新增锁超时合同用例；测试侧持锁辅助为独立实现
# （POSIX fcntl / Windows msvcrt），不复用被测 locking 模块——防自证。
"""E2b 锁超时合同：外部进程持锁 > CLI 重试窗口（10s）→ REGISTRY_BUSY + exit 1。"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

FIX = Path(__file__).resolve().parents[1] / "fixtures"

# 独立持锁辅助（与 hongzhao.locking 无共用代码；两平台分支）
_HOLDER = r"""
import os, sys, time
path = sys.argv[1]
if os.name == "nt":
    import msvcrt
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0))
    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
else:
    import fcntl
    fd = os.open(path, os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
print("held", flush=True)
time.sleep(30)
"""


def _make_kit(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load((FIX / "containment" / "config_base.yaml").read_text(encoding="utf-8"))
    (base / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (base / "raw").mkdir(exist_ok=True)
    (base / "registry").mkdir(exist_ok=True)
    (base / "registry" / "project-registry.yaml").write_text("schema_version: 2\nprojects: []\n", encoding="utf-8")
    (base / "registry" / "knowledge-registry.yaml").write_text("schema_version: 2\nknowledge: []\n", encoding="utf-8")
    return base


def test_registry_busy_when_lock_held(tmp_path):
    from tests.contracts.conftest import build_cmd, run_cli

    kit = _make_kit(tmp_path / "kit")
    proj = tmp_path / "proj"
    proj.mkdir()
    lock_path = kit / ".hongzhao.lock"
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(lock_path)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"  # 辅助已独立持锁
        started = time.monotonic()
        result = run_cli(
            ["project-register", str(proj), "--key", "busyq", "--purpose", "p",
             "--current-state", "s", "--next-action", "n"],
            kit,
            timeout=60,
        )
        elapsed = time.monotonic() - started
        assert result.returncode == 1
        assert "REGISTRY_BUSY" in result.stderr + result.stdout
        assert elapsed >= 9.5  # 确实经历了重试窗口而非立即失败
        # 锁释放后同一命令立即可用（恢复路径）
    finally:
        holder.kill()
        holder.wait(timeout=10)
    result = run_cli(
        ["project-register", str(proj), "--key", "busyq", "--purpose", "p",
         "--current-state", "s", "--next-action", "n"],
        kit,
        timeout=60,
    )
    assert result.returncode == 0
    registry = yaml.safe_load((kit / "registry" / "project-registry.yaml").read_text(encoding="utf-8"))
    assert len(registry["projects"]) == 1
