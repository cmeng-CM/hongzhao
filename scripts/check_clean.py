#!/usr/bin/env python3
"""隐私门（D-17 / A-31）：对仓库工件与 git 历史做外置词表扫描。

词表永不入库（$HONGZHAO_CLEAN_WORDLIST 或 --wordlist 指向）；词表缺失或为空即失败
（词表本身即泄露源）；命中以 [REDACTED] 打码输出并 exit 1；零命中 exit 0。
用法：
  python scripts/check_clean.py --repo . --wordlist <path> [--git-history] [--sdist <pkg-info 或 sdist 目录>]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# 扫描对象白名单后缀（文本工件）；二进制跳过
TEXT_SUFFIXES = {".py", ".md", ".toml", ".yaml", ".yml", ".json", ".txt", ".cfg", ".ini", ".html", ".svg", ""}


def load_wordlist(path: Path) -> list[str]:
    if not path.is_file():
        print(f"error: wordlist missing: {path} (set $HONGZHAO_CLEAN_WORDLIST or pass --wordlist)", file=sys.stderr)
        raise SystemExit(1)
    entries = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    if not entries:
        print(f"error: wordlist is empty: {path}", file=sys.stderr)
        raise SystemExit(1)
    return entries


def redact(text: str, words: list[str]) -> str:
    for word in words:
        text = text.replace(word, "[REDACTED]")
    return text


def scan_repo(repo: Path, words: list[str]) -> list[str]:
    hits: list[str] = []
    for path in sorted(repo.rglob("*")):
        if not path.is_file():
            continue
        parts = {p.name for p in path.parents} | {path.name}
        if {".git", ".delivery", "node_modules", ".venv", "__pycache__"} & parts:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if any(word in line for word in words):
                hits.append(f"{path.relative_to(repo)}:{number}:{redact(line.strip(), words)}")
    return hits


def scan_git_history(repo: Path, words: list[str]) -> list[str]:
    hits: list[str] = []
    if not (repo / ".git").exists():
        return hits
    log = subprocess.run(
        ["git", "log", "--format=%H|%an|%ae|%cn|%ce|%s"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout
    for row in log.splitlines():
        digest, author_name, author_email, committer_name, committer_email, subject = row.split("|", 5)
        for label, value in (
            ("author-name", author_name), ("author-email", author_email),
            ("committer-name", committer_name), ("committer-email", committer_email),
            ("subject", subject),
        ):
            if any(word in value for word in words):
                hits.append(f"git:{digest[:12]}:{label}:{redact(value, words)}")
    return hits


def scan_pkg_info(target: Path, words: list[str]) -> list[str]:
    # 接受 PKG-INFO 文件或 sdist 解包目录（取其中 PKG-INFO）
    candidates = [target] if target.is_file() and target.name == "PKG-INFO" else sorted(target.rglob("PKG-INFO"))
    hits: list[str] = []
    for pkg_info in candidates:
        for number, line in enumerate(pkg_info.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if any(word in line for word in words):
                hits.append(f"{pkg_info}:{number}:{redact(line.strip(), words)}")
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_clean", description="wordlist privacy gate for repo artifacts and git history")
    parser.add_argument("--repo", default=".", help="repository root to scan")
    wordlist_default = os.environ.get("HONGZHAO_CLEAN_WORDLIST")
    parser.add_argument("--wordlist", default=wordlist_default, help="external wordlist path (never committed)")
    parser.add_argument("--git-history", action="store_true", help="also scan commit metadata (names/emails/subjects)")
    parser.add_argument("--sdist", default=None, help="sdist directory or PKG-INFO file to check")
    args = parser.parse_args(argv)
    if not args.wordlist:
        print("error: wordlist missing (set $HONGZHAO_CLEAN_WORDLIST or pass --wordlist)", file=sys.stderr)
        return 1
    words = load_wordlist(Path(args.wordlist))
    repo = Path(args.repo)
    hits = scan_repo(repo, words)
    if args.git_history:
        hits += scan_git_history(repo, words)
    if args.sdist:
        hits += scan_pkg_info(Path(args.sdist), words)
    for hit in hits:
        print(hit)
    print(f"check-clean: {'FAILED (' + str(len(hits)) + ' hits)' if hits else 'ok'}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
