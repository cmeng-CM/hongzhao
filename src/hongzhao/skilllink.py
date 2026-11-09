"""技能目录链接原语（W3，D-W1）：POSIX symlink / Windows junction 统一抽象。

契约见 design W3 表：create/is_link/link_target/remove/replace_existing。
- SkillLinkError(OSError) 携带用户可读文案；bridge 不改错误码、不重组文案；
- 围栏判定（目标是否解析进 <root>/skills）属 bridge 职责，原语不重复——
  `--force` 授权下 bridge 对围栏外/断链链接调用删除属既有语义；
- 删除绝不作用于真实目录（remove 对非链接抛 SkillLinkError）；
- 导入纪律：_winapi 仅在 Windows 分支内条件导入。
"""
from __future__ import annotations

import os
import stat as stat_module
from pathlib import Path

# IO_REPARSE_TAG_MOUNT_POINT 常量为 Python 3.10+ 才进入 stat 模块；3.9 用 Windows SDK 字面值
IO_REPARSE_TAG_MOUNT_POINT = getattr(stat_module, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)


class SkillLinkError(OSError):
    """链接操作失败（目标非链接、文件系统不支持等，消息可直接展示给用户）。"""


def _is_junction(path: Path) -> bool:
    # 3.12+ 有 Path.is_junction；3.9–3.11 走 st_reparse_tag（design C2/W3）
    if hasattr(path, "is_junction"):
        try:
            return path.is_junction()
        except OSError:
            return False
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return getattr(st, "st_reparse_tag", 0) == IO_REPARSE_TAG_MOUNT_POINT


def is_link(path: Path) -> bool:
    """symlink 或 junction（Windows）；不存在返回 False，不抛错。"""
    try:
        return path.is_symlink() or _is_junction(path)
    except OSError:
        return False


def create(target: Path, source: Path) -> None:
    """新建链接；前置：父目录存在且 target 不存在（已存在走 replace_existing）。"""
    target, source = Path(target), Path(source)
    if os.name == "nt":
        import _winapi  # 条件导入（W1/W3 导入纪律）

        try:
            _winapi.CreateJunction(str(source), str(target))
        except OSError as exc:
            raise SkillLinkError(
                f"cannot create junction {target} -> {source}: {exc}; "
                "network or synced drives (e.g. OneDrive) do not support junctions"
            ) from exc
    else:
        try:
            target.symlink_to(source, target_is_directory=True)
        except OSError as exc:
            raise SkillLinkError(f"cannot create symlink {target} -> {source}: {exc}") from exc


def link_target(path: Path) -> Path:
    """穿透解析（symlink/junction 同语义；非链接返回自身 resolve——与现状一致）。"""
    return Path(path).resolve()


def remove(path: Path) -> None:
    """删除链接本体；非链接一律拒绝（绝不删真实目录）。"""
    path = Path(path)
    if not os.path.lexists(path):
        raise FileNotFoundError(str(path))
    if path.is_symlink():
        path.unlink()
        return
    if _is_junction(path):
        path.rmdir()  # junction 必须用 rmdir；对 junction 调 unlink 行为不定（design W3）
        return
    raise SkillLinkError(f"refusing to remove {path}: not a skill link (real directories are never deleted)")


def replace_existing(target: Path, source: Path) -> None:
    """三分支：不存在→create；链接（调用方已判定可删）→remove+create；非链接→拒绝。"""
    target = Path(target)
    if not os.path.lexists(target):
        create(target, source)
        return
    if is_link(target):
        remove(target)
        create(target, source)
        return
    raise SkillLinkError(f"refusing to replace {target}: exists and is not a link")
