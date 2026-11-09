"""跨平台独占锁（W1，D-W2）：POSIX flock / Windows msvcrt.locking。

失败语义（与 contracts.registry_lock 现状逐字等价，见 design W1 表）：
- 打开/创建锁文件失败 → [LOCK_UNWRITABLE] + SystemExit(2)；
- 竞争重试至超时 → [REGISTRY_BUSY] + SystemExit(1)；
- 其余真实 I/O 错误原样抛出（不吞、不改写、不重试）；
- 仅获取成功后 unlock；未获取只 close（LK_UNLCK 要求字节先前已锁定）。
导入纪律：msvcrt 仅在 Windows 分支内条件导入，模块顶层禁止（否则 POSIX ImportError）。
"""
from __future__ import annotations

import errno
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Windows 占用类 errno（msvcrt.locking 竞争；集合由 Windows CI 实测收敛——扩集合不改语义）
_WIN_BUSY_ERRNOS = {errno.EACCES, errno.EDEADLK}


class BusySignal(Exception):
    """锁被其他进程持有（仅驱动重试，不是真实 I/O 错误）。"""


def _try_lock(fd: int) -> None:
    """非阻塞获取；被占用抛 BusySignal，其余 OSError 原样抛出。"""
    if os.name == "nt":
        import msvcrt  # 条件导入（W1 导入纪律）

        os.lseek(fd, 0, os.SEEK_SET)  # 锁区间自当前文件位置起，lock/unlock 前都必须回到 0
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in _WIN_BUSY_ERRNOS:
                raise BusySignal(str(exc)) from exc
            raise
    else:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BusySignal(str(exc)) from exc


def _unlock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def exclusive_lock(path: Path, timeout: float = 10.0):
    lock_path = Path(path)
    try:
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        print(f"[LOCK_UNWRITABLE] cannot create {lock_path}: {exc}", file=sys.stderr)
        raise SystemExit(2)
    deadline = time.monotonic() + timeout
    while True:
        try:
            _try_lock(fd)
            break
        except BusySignal:
            if time.monotonic() >= deadline:
                os.close(fd)  # 未获取：只 close，不 unlock
                print("[REGISTRY_BUSY] another hongzhao process holds the registry lock", file=sys.stderr)
                raise SystemExit(1)
            time.sleep(0.05)
    try:
        yield
    finally:
        # 走到这里必然已获取成功（yield 只在获取后发生）：unlock 后关闭
        try:
            _unlock(fd)
        finally:
            os.close(fd)  # 锁文件持久存在（避免 unlink 竞态），由 .gitignore 忽略
