"""编译后自动提交（git.auto_commit）：把「git 是备份」从手册建议变成默认机制。

边界（与引擎哲学对齐）：
- 纯本地：只调用 git CLI，不做任何网络操作（永不 push）；
- 缺省开启，显式 `auto_commit: false` 关闭；
- 守卫：git 不在 PATH / root 不是 git 仓库 → 打印提示并返回；
  git toplevel ≠ memory root（kit 嵌在更大的仓库里）→ 拒绝提交并提示
  （防止把外层仓库的工作区一并 add -A）；
- 永不阻断编译：任何 git 失败降级为 warning 行，compile 退出码不受影响；
- 提交信息为固定英文格式（可 grep 的机械面文案）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hongzhao import __version__


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    # 与引擎其余部分一致：不捕获 KeyboardInterrupt、显式超时防挂死
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=check,
    )


def maybe_auto_commit(root: Path, config: dict[str, Any], index: dict[str, Any]) -> None:
    """compile 成功写出后调用：按 config.git.auto_commit 决定是否自动提交整个记忆库。"""
    git_conf = (config or {}).get("git") or {}
    # 缺省开启（v0.1 决策：git 是备份的默认姿态）；显式 false 才关闭
    if git_conf.get("auto_commit", True) is not True:
        return
    if shutil.which("git") is None:
        print("warning AUTO_COMMIT_SKIP - git not on PATH; auto-commit disabled for this run")
        return
    if not (root / ".git").exists():
        print("note: auto-commit skipped; memory root is not a git repo (run `git init` to enable)")
        return
    # 围栏：只提交「记忆库自身就是仓库根」的情况；嵌套在外层仓库里时 add -A 会吞掉
    # 外层工作区改动，属于越界写入，宁可不做
    probe = _git(root, "rev-parse", "--show-toplevel", check=False)
    toplevel = probe.stdout.strip() if probe.returncode == 0 else ""
    # F-03：git 输出正斜杠 vs Path.resolve() 反斜杠（Windows）——双侧归一后比较
    same = False
    if toplevel:
        try:
            same = os.path.samefile(toplevel, root)
        except OSError:
            same = os.path.normcase(os.path.realpath(toplevel)) == os.path.normcase(str(root.resolve()))
    if not same:
        print(
            "warning AUTO_COMMIT_SKIP - memory root is nested inside another git repo "
            f"(toplevel: {toplevel or 'unknown'}); keep the kit as a standalone repo to auto-commit"
        )
        return
    staged = _git(root, "add", "-A", ".", check=False)
    if staged.returncode != 0:
        first_line = (staged.stdout + staged.stderr).strip().splitlines()
        print(f"warning AUTO_COMMIT_FAILED - git add: {first_line[0] if first_line else 'unknown error'}")
        return
    # 字节级判空：配合编译幂等（无变化复用时间戳），无差异不产生空提交
    if _git(root, "diff", "--cached", "--quiet", check=False).returncode == 0:
        print("auto-commit: no changes")
        return
    counts = index.get("counts", {})
    message = (
        f"hongzhao compile v{__version__} {index.get('generated_at', '')} "
        f"health={index.get('health', 'unknown')} "
        f"effective={counts.get('effective', 0)} pending={counts.get('pending', 0)}"
    )
    commit = _git(root, "commit", "-m", message, check=False)
    if commit.returncode != 0:
        output = (commit.stdout + commit.stderr).strip()
        first_line = output.splitlines()[0] if output else "unknown git error"
        print(f"warning AUTO_COMMIT_FAILED - {first_line}")
        return
    short = _git(root, "rev-parse", "--short", "HEAD", check=False)
    sha = short.stdout.strip() if short.returncode == 0 else "?"
    print(f"auto-commit: {sha}")
