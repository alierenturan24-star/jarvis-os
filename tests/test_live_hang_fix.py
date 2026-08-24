import builtins
import runpy

from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus
from src.mission.models import Mission
from src.mission.recovery import RecoveryAttemptHistory, recover_task
from src.tools.web_search_tool import WEB_SEARCH_TIMEOUT_SECONDS, WebSearchTool


def test_main_executes_single_line_without_ellipsis_prompt(monkeypatch):
    prompts = []
    executed = []

    class FakeRuntime:
        STOPPED = "STOPPED"

        def __init__(self):
            self.state = "SLEEPING"

        def boot(self):
            pass

        def execute(self, prompt):
            executed.append(prompt)
            self.state = self.STOPPED
            return "ok"

    def fake_input(prompt):
        prompts.append(prompt)
        return "Agent-Reach'i araştır"

    monkeypatch.setattr("src.core.runtime.JarvisRuntime", FakeRuntime)
    monkeypatch.setattr(builtins, "input", fake_input)
    runpy.run_module("main", run_name="__main__")

    assert executed == ["Agent-Reach'i araştır"]
    assert "... " not in prompts


def test_web_search_passes_bounded_timeout_to_ddgs(monkeypatch):
    captured = {}

    class FakeDDGS:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def text(self, query, **kwargs):
            return []

    monkeypatch.setattr("src.tools.web_search_tool.DDGS", FakeDDGS)
    WebSearchTool().search("Agent-Reach")

    assert captured["timeout"] == WEB_SEARCH_TIMEOUT_SECONDS


def test_tool_timeout_is_not_retried_as_provider_failure():
    calls = []
    task = Task(title="browser", agent="browser", handler=lambda task: calls.append(task) or "ok")
    task.status = TaskStatus.FAILED
    task.result = TaskResult(success=False, error="timeout")

    attempts = recover_task(
        task,
        Mission(title="Agent-Reach"),
        provider_manager=type("PM", (), {})(),
        job_manager=type("JM", (), {"run_task": lambda self, task: calls.append(task)})(),
        history=RecoveryAttemptHistory(),
    )

    assert attempts == []
    assert calls == []
