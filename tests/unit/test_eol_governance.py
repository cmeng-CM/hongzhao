"""E8/E14：行尾治理验收（Windows 主战场；POSIX 上 autocrlf 对 LF 文件为 no-op，同样应绿）。

- E8：auto-commit 在 autocrlf true/false 两组下、强制重检出后仍收敛到稳态（无仅行尾 diff）
- E14：autocrlf=true 环境下 git clone 已含产物的 kit 后，skills-install 不误报 SKILL_MODIFIED
      （.gitattributes 的 eol=lf 下界保护字节比较——design W4/F-08）
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from hongzhao.bridge import cmd_skills_install, sync_package_to_root
from hongzhao.render import compile_all
from hongzhao.scaffold import GITATTRIBUTES

FIX = Path(__file__).resolve().parents[1] / "fixtures"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git CLI not available")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)


def _init_repo(root: Path, autocrlf: str) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "hongzhao-test")
    _git(root, "config", "core.autocrlf", autocrlf)


def _commit_count(root: Path) -> int:
    return int(_git(root, "rev-list", "--count", "--all").stdout.strip())


def _make_kit(base: Path, auto_commit: bool, with_client: bool = False) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load((FIX / "containment" / "config_base.yaml").read_text(encoding="utf-8"))
    if auto_commit:
        config["git"] = {"auto_commit": True}
    if with_client:
        skills_root = base / "client-skills"
        skills_root.mkdir(exist_ok=True)
        config["clients"] = {"cc": {"enabled": True, "bridge_path": str(base / "cc.md"),
                                    "skills_root": str(skills_root), "mode": "inline"}}
    (base / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (base / "raw").mkdir(exist_ok=True)
    (base / "registry").mkdir(exist_ok=True)
    (base / "registry" / "project-registry.yaml").write_text("schema_version: 2\nprojects: []\n", encoding="utf-8")
    (base / "registry" / "knowledge-registry.yaml").write_text("schema_version: 2\nknowledge: []\n", encoding="utf-8")
    (base / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8", newline="")  # init 形态：下界随 kit 落盘
    return base


@pytest.mark.parametrize("autocrlf", ["true", "false"])
def test_e8_auto_commit_steady_state_under_both_autocrlf(tmp_path, autocrlf):
    # E8：两组显式 autocrlf + 强制重检出；稳态（第 3 次编译）后无新提交，提交确实发生过
    kit = _make_kit(tmp_path / "kit", auto_commit=True)
    assert sync_package_to_root(kit) == 0  # init 形态：包内 skills/templates 已就位（LF 字节）
    _init_repo(kit, autocrlf)
    compile_all(kit)  # 提交 1：全部产物
    compile_all(kit)  # 提交 2：diff 报告进入稳态叙事
    compile_all(kit)  # 稳态：字节全等
    # 强制重新检出（重演 clone 后的检出形态），再编译一次仍应零新提交
    _git(kit, "add", "-A", ".")
    files = [ln for ln in _git(kit, "ls-files").stdout.splitlines() if ln]
    for rel in files:
        (kit / rel).unlink()
    _git(kit, "checkout", "--", ".")
    compile_all(kit)
    compile_all(kit)
    assert _commit_count(kit) == 2  # 稳态后零新提交
    # 重检出后工作区 skills 文件仍为 LF（eol=lf 下界；autocrlf=true 也不改检出形态）
    skills = sorted((kit / "skills").rglob("SKILL.md"))
    assert skills and all(b"\r" not in s.read_bytes() for s in skills)


def test_e14_clone_then_skills_install_no_modified(tmp_path):
    # E14：autocrlf=true 下 clone 已含产物的 kit，skills-install 不得误报 SKILL_MODIFIED
    source = _make_kit(tmp_path / "src", auto_commit=False, with_client=True)
    compile_all(source)
    _init_repo(source, "true")
    _git(source, "add", "-A", ".")
    _git(source, "commit", "-q", "-m", "kit with products")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", "-c", "core.autocrlf=true", str(source), str(clone))
    _git(clone, "config", "core.autocrlf", "true")
    # 克隆出的 kit 指向自身目录内的假客户端（config 里是绝对路径，指向源 kit——改指克隆目录）
    config = yaml.safe_load((clone / "config.yaml").read_text(encoding="utf-8"))
    skills_root = clone / "client-skills"
    config["clients"]["cc"]["skills_root"] = str(skills_root)
    config["clients"]["cc"]["bridge_path"] = str(clone / "cc.md")
    (clone / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    assert cmd_skills_install(clone, "cc") == 0  # 无 SKILL_MODIFIED、无 .new
    assert not list((clone / "skills").rglob("*.new"))
