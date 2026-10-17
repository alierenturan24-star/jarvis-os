from __future__ import annotations

import json
import os
import time

import pytest

from src.control_center.server import ControlCenterInstanceLock


def test_stale_lock_with_reused_live_pid_is_recovered_when_port_is_closed(tmp_path):
    lock = ControlCenterInstanceLock("127.0.0.1", 49871, tmp_path)
    lock.path.write_text(
        json.dumps({"pid": os.getpid(), "created_at": time.time() - 120}),
        encoding="utf-8",
    )

    lock.acquire()
    try:
        owner = json.loads(lock.path.read_text(encoding="utf-8"))
        assert owner["pid"] == os.getpid()
        assert lock.acquired is True
    finally:
        lock.release()

    assert not lock.path.exists()


def test_recent_live_lock_is_not_stolen_during_startup(tmp_path):
    lock = ControlCenterInstanceLock("127.0.0.1", 49872, tmp_path)
    lock.path.write_text(
        json.dumps({"pid": os.getpid(), "created_at": time.time()}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="already running"):
        lock.acquire()
