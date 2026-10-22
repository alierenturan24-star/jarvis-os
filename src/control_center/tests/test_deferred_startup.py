from __future__ import annotations

import threading
import time

from src.control_center.server import DeferredControlCenterService


def test_deferred_service_exposes_liveness_before_heavy_factory_finishes(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setenv("JARVIS_BUILD_ID", "startup-test-build")

    class SlowService:
        def __init__(self):
            started.set()
            assert release.wait(timeout=3)

        def liveness(self):
            return {
                "backend_alive": True,
                "runtime_state": "SLEEPING",
                "process": {"build_identity": "startup-test-build"},
            }

        def health(self):
            return self.liveness()

        def scheduler_tick(self):
            return None

    deferred = DeferredControlCenterService(factory=SlowService)
    deferred.start()

    assert started.wait(timeout=1)
    live = deferred.liveness()
    assert live["backend_alive"] is True
    assert live["runtime_state"] == "BOOTING"
    assert live["startup_ready"] is False
    assert live["startup_stage"] == "constructing_control_center_service"
    assert live["process"]["build_identity"] == "startup-test-build"

    release.set()
    deadline = time.monotonic() + 3
    while not deferred.startup_ready and time.monotonic() < deadline:
        time.sleep(0.01)

    assert deferred.startup_ready is True
    ready = deferred.liveness()
    assert ready["runtime_state"] == "SLEEPING"
    assert ready["startup_ready"] is True
    assert ready["startup_stage"] == "ready"


def test_deferred_service_surfaces_startup_error_without_dying():
    class BrokenService:
        def __init__(self):
            raise RuntimeError("synthetic startup failure")

    deferred = DeferredControlCenterService(factory=BrokenService)
    deferred.start()

    deadline = time.monotonic() + 2
    while not deferred.startup_error and time.monotonic() < deadline:
        time.sleep(0.01)

    live = deferred.liveness()
    assert live["backend_alive"] is True
    assert live["runtime_state"] == "STARTUP_ERROR"
    assert live["startup_ready"] is False
    assert "synthetic startup failure" in live["startup_error"]
