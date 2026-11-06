"""rc6 修复回归：C1 dry-run 零写入 / C4 未来日期 warning / O6 bridge 前置指引 / C2 提示语法。"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import yaml

from hongzhao.bridge import cmd_bridge_install
from hongzhao.cli import main as cli_main
from hongzhao.contracts import cmd_register
from hongzhao.render import compile_all

FIX = Path(__file__).resolve().parents[1] / "fixtures"
BASE = (FIX / "containment" / "config_base.yaml").read_text(encoding="utf-8")


def make_kit(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.yaml").write_text(BASE, encoding="utf-8")
    (base / "raw").mkdir(exist_ok=True)
    (base / "registry").mkdir(exist_ok=True)
    (base / "registry" / "project-registry.yaml").write_text("schema_version: 2\nprojects: []\n", encoding="utf-8")
    (base / "registry" / "knowledge-registry.yaml").write_text("schema_version: 2\nknowledge: []\n", encoding="utf-8")
    return base


def test_c1_dry_run_register_writes_nothing(tmp_path, capsys):
    kit = make_kit(tmp_path / "kit")
    proj = tmp_path / "proj"
    proj.mkdir()
    args = {"key": "dryq", "purpose": "p", "current_state": "s", "next_action": "n"}
    code = cmd_register(kit, str(proj), args, dry_run=True)
    out = capsys.readouterr().out
    assert code == 0
    assert "dry-run:" in out and "no files written" in out
    # 零写入：registry 仍空、无 projects/ 目录
    reg = yaml.safe_load((kit / "registry" / "project-registry.yaml").read_text(encoding="utf-8"))
    assert reg["projects"] == []
    assert not (kit / "projects").exists()
    # 真实执行（无 dry_run）仍正常落盘
    code = cmd_register(kit, str(proj), args)
    assert code == 0
    assert (kit / "projects" / "dryq" / "project-view.md").is_file()


FUTURE_RAW = """---
schema_version: 2
id: mem-1234ffff-0000-4000-8000-00000000000f
created: 2099-01-01
source: user
topic: future
kind: memory
scope: non-project
activation: on-demand
record_type: source
summary: 未来日期记录
compile_status: new
---
x
"""


def test_c4_future_created_is_warning_not_block(tmp_path, capsys):
    kit = make_kit(tmp_path / "kit")
    (kit / "raw" / "future.md").write_text(FUTURE_RAW, encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli_main(["--root", str(kit), "validate"])
    out = buf.getvalue()
    assert code == 0  # warning 不阻断
    assert "created is in the future" in out
    assert "validation: review-needed" in out  # 候选仍合法入库


def test_o6_bridge_before_compile_gives_actionable_hint(tmp_path, capsys):
    kit = make_kit(tmp_path / "kit")  # 未 compile → 无 render/bootstrap.md
    code = cmd_bridge_install(kit, "all")
    err = capsys.readouterr().err
    assert code == 1
    assert "[OUTPUT_MISSING]" in err and "run `hongzhao compile` first" in err


def test_c2_legacy_hint_has_correct_syntax(tmp_path, capsys):
    # 行为验证：legacy 块在场时 doctor 提示 migrate-bridge 且不带非法参数 all
    kit = make_kit(tmp_path / "kit")
    fake = tmp_path / "fake-client.md"
    fake.write_text("own\n<!-- agent-memory:start -->\nold block\n<!-- agent-memory:end -->\n", encoding="utf-8")
    cfg = yaml.safe_load((kit / "config.yaml").read_text(encoding="utf-8"))
    cfg.setdefault("clients", {})["fake_cc"] = {
        "enabled": True,
        "bridge_path": str(fake),
        "skills_root": str(tmp_path / "fake-skills"),
        "mode": "inline",
    }
    (kit / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    compile_all(kit)  # 产物就绪
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(["--root", str(kit), "doctor"])
    out = buf.getvalue()
    assert "LEGACY_MARKER" in out
    assert "migrate-bridge (no arguments)" in out
    assert "migrate-bridge all" not in out
