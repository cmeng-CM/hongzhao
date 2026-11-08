"""git.auto_commit 回归：校验 / 入库提交 / 无变更不空提交 / 非仓库与嵌套仓库守卫 / 默认关闭。"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from hongzhao.core import load_config
from hongzhao.render import compile_all

FIX = Path(__file__).resolve().parents[1] / "fixtures"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git CLI not available")


def make_kit(base: Path, git_conf: dict | None) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load((FIX / "containment" / "config_base.yaml").read_text(encoding="utf-8"))
    if git_conf is not None:
        config["git"] = git_conf
    (base / "config.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (base / "raw").mkdir(exist_ok=True)
    (base / "registry").mkdir(exist_ok=True)
    (base / "registry" / "project-registry.yaml").write_text("schema_version: 2\nprojects: []\n", encoding="utf-8")
    (base / "registry" / "knowledge-registry.yaml").write_text("schema_version: 2\nknowledge: []\n", encoding="utf-8")
    return base


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)


def commit_count(root: Path) -> int:
    # --all：空仓库（无任何提交）返回 0 而不是报错
    out = git(root, "rev-list", "--count", "--all").stdout.strip()
    return int(out)


def init_repo(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "hongzhao-test")


def test_config_git_section_validation(tmp_path):
    # 未知键与类型错误均被拒绝；合法段可通过
    kit = make_kit(tmp_path / "kit", {"auto_commit": True, "push": False})
    with pytest.raises(ValueError, match="git unknown fields: push"):
        load_config(kit)
    kit = make_kit(tmp_path / "kit2", {"auto_commit": "yes"})
    with pytest.raises(ValueError, match="git.auto_commit must be a boolean"):
        load_config(kit)
    kit = make_kit(tmp_path / "kit3", {"auto_commit": True})
    assert load_config(kit)["git"] == {"auto_commit": True}


def test_auto_commit_creates_commit(tmp_path, capsys):
    kit = make_kit(tmp_path / "kit", {"auto_commit": True})
    init_repo(kit)
    compile_all(kit)
    assert commit_count(kit) == 1
    message = git(kit, "log", "-1", "--format=%s").stdout
    assert message.startswith("hongzhao compile v") and "health=" in message
    assert "auto-commit:" in capsys.readouterr().out


def test_auto_commit_no_empty_commit(tmp_path, capsys):
    kit = make_kit(tmp_path / "kit", {"auto_commit": True})
    init_repo(kit)
    compile_all(kit)  # 提交 1：全部产物
    compile_all(kit)  # 提交 2：diff 报告从「first compile」叙事转入稳态（合法变更）
    compile_all(kit)  # 稳态无操作：字节全等，不再提交
    compile_all(kit)
    assert commit_count(kit) == 2
    assert "auto-commit: no changes" in capsys.readouterr().out


def test_auto_commit_enabled_by_default(tmp_path, capsys):
    # 不写 git 段（老 kit 形态）：独立 git 仓库时缺省即自动提交
    kit = make_kit(tmp_path / "kit", None)
    init_repo(kit)
    compile_all(kit)
    assert commit_count(kit) == 1
    assert "auto-commit:" in capsys.readouterr().out


def test_auto_commit_explicit_false_disables(tmp_path, capsys):
    kit = make_kit(tmp_path / "kit", {"auto_commit": False})
    init_repo(kit)
    compile_all(kit)
    assert commit_count(kit) == 0
    assert "auto-commit" not in capsys.readouterr().out


def test_auto_commit_skips_when_not_repo(tmp_path, capsys):
    kit = make_kit(tmp_path / "kit", {"auto_commit": True})
    compile_all(kit)  # 未 git init：提示并跳过，编译不受影响
    out = capsys.readouterr().out
    assert "not a git repo" in out
    assert (kit / "compiled" / "memory-index.yaml").exists()


def test_compile_noop_is_byte_stable(tmp_path):
    # 无操作编译复用基线时间戳：两次编译产物字节一致（byte-reproducible）
    kit = make_kit(tmp_path / "kit", None)
    compile_all(kit)
    probe = kit / "compiled" / "memory-index.yaml"
    first = probe.read_bytes()
    compile_all(kit)
    assert probe.read_bytes() == first


def test_auto_commit_nested_repo_guard(tmp_path, capsys):
    # kit 嵌在外层仓库里（自身无 .git）：绝不触碰外层仓库历史
    outer = tmp_path / "outer"
    outer.mkdir()
    init_repo(outer)
    kit = make_kit(outer / "kit", {"auto_commit": True})
    compile_all(kit)
    assert commit_count(outer) == 0
    assert "not a git repo" in capsys.readouterr().out
