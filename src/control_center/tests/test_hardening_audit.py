import os
import time

import pytest

from src.control_center.server import ControlCenterInstanceLock
from src.control_center.service import ControlCenterService
from src.control_center.store import ControlCenterStore
from src.core.runtime import JarvisRuntime
from src.agents.chat_agent import ChatAgent
from src.planner.task import Task
from src.providers.provider_manager import RouteResult


class ExplodingJarvis:
    last_mission = None
    last_provider_route = None

    def chat(self, message, execution_hints=None):
        raise ValueError("provider exploded")


def test_second_control_center_instance_is_rejected_and_stale_lock_recovers(tmp_path):
    first = ControlCenterInstanceLock("127.0.0.1", 8765, tmp_path)
    second = ControlCenterInstanceLock("127.0.0.1", 8765, tmp_path)
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_runtime_exception_is_persisted_as_blocked_not_completed(tmp_path):
    runtime = JarvisRuntime()
    runtime.jarvis = ExplodingJarvis()
    runtime.boot()
    service = ControlCenterService(runtime=runtime, store=ControlCenterStore(tmp_path / "state.json"))

    record = {"id": "failure-1", "goal": "hello", "source": "text", "status": "QUEUED",
              "stage": "UNDERSTANDING", "worker": "", "progress": 0, "created_at": "now"}
    service.store.append("missions", dict(record))
    service._active = record
    service._run_command(record)

    saved = next(row for row in service.store.snapshot()["missions"] if row["id"] == "failure-1")
    assert saved["status"] == "BLOCKED"
    assert "provider exploded" in saved["error_context"]
    assert runtime.completed_tasks == 0


def test_health_exposes_real_process_identity(tmp_path):
    service = ControlCenterService(store=ControlCenterStore(tmp_path / "state.json"))
    process = service.health()["process"]
    assert process["pid"] == os.getpid()
    assert process["instance_id"] == service._started_at
    assert process["runtime_started_at"]


def test_chat_prompt_contains_true_runtime_time_and_state():
    agent = ChatAgent()
    captured = {}
    def route_and_generate(**kwargs):
        captured.update(kwargs)
        return RouteResult("ok", "fake", "fake", "test", False, 0.0, True, ("fake",))
    agent.router.manager.route_and_generate = route_and_generate
    agent.runtime_context_provider = lambda: {
        "local_date": "2026-08-18", "local_datetime": "2026-08-18T12:00:00+02:00",
        "timezone": "CEST", "runtime_state": "WORKING", "runtime_pid": 123,
    }
    task = Task(agent="chat", action="chat", target="Bugün ne, sistem durumu nedir?")
    answer = agent.execute(task)
    assert answer.endswith("ok")
    assert "yerel tarih/saat=2026-08-18T12:00:00+02:00" in answer
    assert "2026-08-18" in captured["system"]
    assert "12:00:00+02:00" in captured["system"]
    assert '"timezone": "CEST"' in captured["system"]
    assert '"runtime_state": "WORKING"' in captured["system"]
    assert '"runtime_pid": 123' in captured["system"]
    assert "tahmin etme" in captured["system"]
    assert "authoritative" in captured["system"]
    assert "bilinmiyor" in captured["system"]


def _runtime_grounded_answer(provider_output):
    agent = ChatAgent()
    agent.runtime_context_provider = lambda: {
        "local_date": "2026-08-19", "local_datetime": "2026-08-19T01:04:43+02:00",
        "timezone": "Europe/Berlin", "runtime_state": "WORKING", "runtime_pid": 18000,
        "runtime_started_at": "2026-08-19T01:04:43+02:00", "last_error": None,
        "last_mission_status": None,
    }
    agent.router.manager.route_and_generate = lambda **kwargs: RouteResult(
        provider_output, "fake", "fake", "test", False, 0.0, True, ("fake",),
    )
    return agent.execute(Task(
        agent="chat", action="chat",
        target="Bugünün gerçek tarihini ve kısa runtime sistem durumunu belirt.",
    ))


def test_wrong_provider_date_cannot_override_authoritative_runtime_date():
    answer = _runtime_grounded_answer(
        "Bugün 19 Haziran 2026. Sistem 19 Haziran 2026 tarihinde başlatıldı; "
        "runtime_state: WORKING, işlem kimliği 18000.",
    )
    assert "2026-08-19T01:04:43+02:00" in answer
    assert "19 Haziran 2026" not in answer
    assert "çeliştiği için gösterilmedi" in answer


def test_correct_provider_runtime_answer_is_preserved_after_fact_header():
    provider_output = "Bugün 19 Ağustos 2026; runtime_state: WORKING, PID 18000."
    answer = _runtime_grounded_answer(provider_output)
    assert answer.endswith(provider_output)
    assert "2026-08-19T01:04:43+02:00" in answer


def test_all_provider_failure_becomes_controlled_blocked(tmp_path):
    runtime = JarvisRuntime(); runtime.boot()
    chat = runtime.jarvis.agent_router.registry.get("chat")
    chat.router.manager.route_and_generate = lambda **kwargs: RouteResult(
        "provider failure", "ollama", "gemini", "failed", True, 0.1, False,
        ("ollama", "gemini"),
    )
    service = ControlCenterService(runtime=runtime, store=ControlCenterStore(tmp_path / "state.json"))
    record = {"id": "all-fail", "goal": "hello", "source": "text", "status": "QUEUED",
              "stage": "UNDERSTANDING", "worker": "", "progress": 0, "created_at": "now"}
    service.store.append("missions", dict(record)); service._active = record
    service._run_command(record)
    saved = next(row for row in service.store.snapshot()["missions"] if row["id"] == "all-fail")
    assert saved["status"] == "BLOCKED"
    assert "ollama -> gemini" in saved["error_context"]
