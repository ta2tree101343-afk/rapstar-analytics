import multiprocessing
from pathlib import Path

import pytest

from collector.lock import LockBusyError, exclusive_lock


def _hold_lock(lock_path_str, ready_evt, release_evt):
    with exclusive_lock(Path(lock_path_str)):
        ready_evt.set()
        release_evt.wait(timeout=10)


def test_second_acquire_raises(tmp_path):
    lock = tmp_path / "collect.lock"
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    release = ctx.Event()
    p = ctx.Process(target=_hold_lock, args=(str(lock), ready, release))
    p.start()
    try:
        assert ready.wait(timeout=10), "child failed to acquire lock"
        with pytest.raises(LockBusyError):
            with exclusive_lock(lock):
                pass
    finally:
        release.set()
        p.join(timeout=10)
        assert p.exitcode == 0


def test_release_allows_reacquire(tmp_path):
    lock = tmp_path / "collect.lock"
    with exclusive_lock(lock):
        pass
    with exclusive_lock(lock):
        pass


def test_lock_creates_parent_dir(tmp_path):
    lock = tmp_path / "nested" / "dir" / "collect.lock"
    with exclusive_lock(lock):
        assert lock.exists()
