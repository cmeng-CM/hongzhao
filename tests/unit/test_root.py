"""根发现四源测试（ ①–⑥ + CONFIG_INVALID 不回落 + ROOT_AMBIGUOUS + root --json 契约）。

全部数据合成；bridge 用例通过替换 PRESET_BRIDGE_PATHS 指向临时文件，绝不触碰真实
客户端全局文件（~/.claude/CLAUDE.md 等）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hongzhao import root as rootmod

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "root_discovery"
VALID = (FIX / "config_valid.yaml").read_text(encoding="utf-8")
NO_FEATURE = (FIX / "config_no_feature.yaml").read_text(encoding="utf-8")
BAD = (FIX / "config_bad.yaml").read_text(encoding="utf-8")


def make_kit(base: Path, config_text: str = VALID) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.yaml").write_text(config_text, encoding="utf-8")
    (base / "raw").mkdir(exist_ok=True)
    (base / "registry").mkdir(exist_ok=True)
    return base


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    # 隔离：无环境根、中性 cwd、bridge 表指向不存在的临时路径
    monkeypatch.delenv("HONGZHAO_ROOT", raising=False)
    (tmp_path / "neutral").mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path / "neutral")
    monkeypatch.setattr(rootmod, "PRESET_BRIDGE_PATHS", (str(tmp_path / "no-such-bridge.md"),))


def test_explicit_root(tmp_path):
    kit = make_kit(tmp_path / "kit")
    root, source = rootmod.discover_root(explicit=str(kit))
    assert root == kit.resolve()
    assert source == "--root"


def test_env_root(tmp_path, monkeypatch):
    kit = make_kit(tmp_path / "kit")
    monkeypatch.setenv("HONGZHAO_ROOT", str(kit))
    root, source = rootmod.discover_root()
    assert root == kit.resolve()
    assert source == "env"


def test_cwd_walk_up_hits(tmp_path, monkeypatch):
    kit = make_kit(tmp_path / "deep" / "kit")
    monkeypatch.chdir(kit / "raw")
    root, source = rootmod.discover_root()
    assert root == kit.resolve()
    assert source == "cwd"


def test_cwd_no_feature_continues(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "config.yaml").write_text(NO_FEATURE, encoding="utf-8")
    (plain / "sub").mkdir()
    monkeypatch.chdir(plain / "sub")
    assert rootmod._from_cwd(Path.cwd()) is None


def test_cwd_bad_config_invalid_no_fallback(tmp_path, monkeypatch):
    # 有特征键但校验失败 → CONFIG_INVALID；且即使存在有效托管块也不回落（cwd 优先+停止）
    bad = make_kit(tmp_path / "bad", config_text=BAD)
    good = make_kit(tmp_path / "good")
    bridge = tmp_path / "bridge.md"
    bootstrap = good / "render"
    bootstrap.mkdir(exist_ok=True)
    (bootstrap / "bootstrap.md").write_text("snapshot", encoding="utf-8")
    bridge.write_text(
        f"<!-- hongzhao:start -->\n@{bootstrap / 'bootstrap.md'}\n<!-- hongzhao:end -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rootmod, "PRESET_BRIDGE_PATHS", (str(bridge),))
    monkeypatch.chdir(bad / "raw")
    with pytest.raises(rootmod.RootError) as excinfo:
        rootmod.discover_root()
    assert excinfo.value.code == "CONFIG_INVALID"


def test_bridge_import_mode(tmp_path, monkeypatch):
    kit = make_kit(tmp_path / "kit2")
    snap = kit / "render"
    snap.mkdir(exist_ok=True)
    (snap / "bootstrap.md").write_text("managed", encoding="utf-8")
    bridge = tmp_path / "client.md"
    bridge.write_text(
        f"<!-- hongzhao:start -->\n@{snap / 'bootstrap.md'}\n<!-- hongzhao:end -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rootmod, "PRESET_BRIDGE_PATHS", (str(bridge),))
    root, source = rootmod.discover_root()
    assert root == kit.resolve()
    assert source == "bridge"


def test_bridge_inline_mode(tmp_path, monkeypatch):
    kit = make_kit(tmp_path / "kit3")
    bridge = tmp_path / "client.md"
    bridge.write_text(
        f"<!-- hongzhao:start -->\n---\nmemory_root: {kit}\n---\nsnapshot body\n<!-- hongzhao:end -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rootmod, "PRESET_BRIDGE_PATHS", (str(bridge),))
    root, source = rootmod.discover_root()
    assert root == kit.resolve()
    assert source == "bridge"


def test_bridge_ambiguous(tmp_path, monkeypatch):
    kit_a = make_kit(tmp_path / "a")
    kit_b = make_kit(tmp_path / "b")
    bridge_a = tmp_path / "ca.md"
    bridge_a.write_text(
        f"<!-- agent-memory:start -->\n---\nmemory_root: {kit_a}\n---\n<!-- agent-memory:end -->\n",
        encoding="utf-8",
    )
    bridge_b = tmp_path / "cb.md"
    bridge_b.write_text(
        f"<!-- hongzhao:start -->\n---\nmemory_root: {kit_b}\n---\n<!-- hongzhao:end -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rootmod, "PRESET_BRIDGE_PATHS", (str(bridge_a), str(bridge_b)))
    with pytest.raises(rootmod.RootError) as excinfo:
        rootmod.discover_root()
    assert excinfo.value.code == "ROOT_AMBIGUOUS"
    assert len(excinfo.value.candidates) == 2


def _sandbox_env(tmp_path):
    # 子进程必须隔离 HOME：真实 ~/.claude/CLAUDE.md 等含托管块，会把测试引向生产库
    home = tmp_path / "fake-home"
    home.mkdir(exist_ok=True)
    return {"PATH": __import__("os").environ["PATH"], "HOME": str(home)}


def test_root_json_contract(tmp_path, monkeypatch):
    kit = make_kit(tmp_path / "kit")
    code = (
        "from hongzhao.cli import main; import sys; "
        "raise SystemExit(main(['--json', 'root']))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=str(kit / "raw"), env=_sandbox_env(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["root"] == str(kit.resolve())
    assert payload["source"] == "cwd"
    assert payload["config"].endswith("config.yaml")


def test_bad_config_reports_fatal_exit2(tmp_path):
    # -M1：坏 config 在普通命令下必须干净报错 + exit 2（不吐 traceback）
    bad = make_kit(tmp_path / "bad", config_text=BAD)
    code = (
        "from hongzhao.cli import main; import sys; "
        f"raise SystemExit(main(['--root', {str(bad)!r}, 'validate']))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=str(REPO), env=_sandbox_env(tmp_path),
    )
    assert proc.returncode == 2
    assert "fatal:" in proc.stderr or "[CONFIG_INVALID]" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_root_subcommand_accepts_trailing_json_and_root(tmp_path):
    # 设计 ：`hongzhao root [--json]`——旗标允许在子命令后；--root 透传给 root 子命令
    kit = make_kit(tmp_path / "kit")
    code = (
        "from hongzhao.cli import main; import sys; "
        f"raise SystemExit(main(['--root', {str(kit)!r}, 'root', '--json']))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=str(REPO), env=_sandbox_env(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["root"] == str(kit.resolve())
    assert payload["source"] == "--root"
