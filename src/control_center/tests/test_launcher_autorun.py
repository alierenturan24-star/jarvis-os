from __future__ import annotations

import pytest

from src.control_center.service import _goal_forbids_auto_publish
from src.control_center.tests.test_youtube_queue_dispatch import (
    connect, fake_mission, new_service, wait,
)


def test_launch_with_empty_queue_is_noop(tmp_path):
    service, runtime = new_service(tmp_path)
    assert service.run_queued_on_launch() == {"started": False, "reason": "NO_QUEUED_YOUTUBE_GOAL"}
    assert runtime.received == []


def test_launch_dispatches_once_without_auto_publish(tmp_path):
    service, runtime = new_service(tmp_path)
    connect(service)
    runtime.jarvis.last_mission = fake_mission(tasks=[])
    goal = "Swiss Insider icin gercek Shorts uret."
    queued = service.enqueue_youtube(goal)
    result = service.run_queued_on_launch()
    assert result["started"] is True
    wait(service)
    assert len(runtime.received) == 1
    assert goal in runtime.received[0]
    assert _goal_forbids_auto_publish(runtime.received[0])
    assert service.store.snapshot()["engines"]["youtube"]["queue"][0]["status"] == "DISPATCHED"
    assert service.run_queued_on_launch()["started"] is False
    assert len(runtime.received) == 1


def test_launch_retains_queue_when_youtube_account_is_not_connected(tmp_path):
    service, runtime = new_service(tmp_path)
    service.enqueue_youtube("Shorts uret.")
    with pytest.raises(RuntimeError, match="NO_CONNECTED_YOUTUBE_ACCOUNT"):
        service.run_queued_on_launch()
    assert service.store.snapshot()["engines"]["youtube"]["queue"][0]["status"] == "QUEUED"
    assert runtime.received == []


def test_launch_does_not_override_pause(tmp_path):
    service, runtime = new_service(tmp_path)
    service.enqueue_youtube("Shorts uret.")
    service.pause()
    assert service.run_queued_on_launch()["reason"] == "JARVIS_PAUSED_OR_STOPPED"
    assert runtime.received == []
