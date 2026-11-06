"""隐私门测试//：dummy 词表 + 合成泄漏仓库；绝不使用真实词表）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_clean.py"


def run(args: list[str], env_extra: dict | None = None) -> subprocess.CompletedProcess:
    import os

    env = {k: v for k, v in os.environ.items() if k != "HONGZHAO_CLEAN_WORDLIST"}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env)


def make_leak_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("clean text\n", encoding="utf-8")
    (repo / "leak.md").write_text("contact zhang-san-secret for details\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=leiaked-name", "-c", "user.email=leiaked@example.invalid", "commit", "-q", "-m", "leak in subject"],
        cwd=repo, check=True,
    )
    return repo


def test_wordlist_missing_and_empty_fail(tmp_path):
    result = run(["--repo", str(tmp_path), "--wordlist", str(tmp_path / "nope.txt")])
    assert result.returncode == 1 and "wordlist missing" in result.stderr
    empty = tmp_path / "empty.txt"
    empty.write_text("# only comments\n", encoding="utf-8")
    result = run(["--repo", str(tmp_path), "--wordlist", str(empty)])
    assert result.returncode == 1 and "empty" in result.stderr


def test_hit_redacted_and_exit1(tmp_path):
    repo = make_leak_repo(tmp_path)
    wordlist = tmp_path / "wl.txt"
    wordlist.write_text("zhang-san-secret\nleiaked-name\nleiaked@example.invalid\n", encoding="utf-8")
    result = run(["--repo", str(repo), "--wordlist", str(wordlist)])
    assert result.returncode == 1
    assert "[REDACTED]" in result.stdout
    assert "zhang-san-secret" not in result.stdout  # 命中输出本身不回显敏感词
    assert "leak.md:1:" in result.stdout


def test_zero_hit_exit0(tmp_path):
    repo = make_leak_repo(tmp_path)
    wordlist = tmp_path / "wl.txt"
    wordlist.write_text("totally-absent-word\n", encoding="utf-8")
    result = run(["--repo", str(repo), "--wordlist", str(wordlist)])
    assert result.returncode == 0 and "check-clean: ok" in result.stdout


def test_git_history_scans_commit_metadata(tmp_path):
    repo = make_leak_repo(tmp_path)
    wordlist = tmp_path / "wl.txt"
    wordlist.write_text("leiaked-name\nleiaked@example.invalid\n", encoding="utf-8")
    result = run(["--repo", str(repo), "--wordlist", str(wordlist), "--git-history"])
    assert result.returncode == 1
    assert "author-name" in result.stdout and "author-email" in result.stdout
    assert "[REDACTED]" in result.stdout


def test_sdist_pkg_info_check(tmp_path):
    sdist = tmp_path / "dist"
    (sdist / "hongzhao-0.0.0.dev0").mkdir(parents=True)
    (sdist / "hongzhao-0.0.0.dev0" / "PKG-INFO").write_text(
        "Metadata-Version: 2.1\nName: hongzhao\nAuthor: real-leiaked-person\nAuthor-email: real@work.example.invalid\n",
        encoding="utf-8",
    )
    wordlist = tmp_path / "wl.txt"
    wordlist.write_text("real-leiaked-person\nreal@work.example.invalid\n", encoding="utf-8")
    (tmp_path / "empty-repo").mkdir()
    result = run(["--repo", str(tmp_path / "empty-repo"), "--wordlist", str(wordlist), "--sdist", str(sdist)])
    assert result.returncode == 1
    assert "PKG-INFO" in result.stdout and "[REDACTED]" in result.stdout
