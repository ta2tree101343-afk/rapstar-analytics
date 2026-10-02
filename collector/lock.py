from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path


class LockBusyError(RuntimeError):
    """Raised when another process already holds the lock."""


@contextmanager
def exclusive_lock(lock_path: Path):
    """Advisory exclusive file lock. Non-blocking; raises LockBusyError if held.

    The lock file persists across runs; only the flock releases automatically
    when the file descriptor closes (including process crash), so a leftover
    file does not block future runs.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "a+")
    try:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            raise LockBusyError(f"別プロセスが既に実行中です (lock={lock_path})")
        f.seek(0)
        f.truncate()
        f.write(str(os.getpid()))
        f.flush()
        try:
            yield
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            finally:
                f.close()
    except Exception:
        try:
            f.close()
        except Exception:
            pass
        raise
