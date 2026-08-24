from __future__ import annotations

from src.mission.department_orchestrator import (
    CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS,
    DEPARTMENT_TASK_TIMEOUT_SECONDS,
    DepartmentOrchestrator,
)
from src.mission.models import Mission
from src.providers.claude_code_provider import DEFAULT_TIMEOUT_SECONDS as CLAUDE_CODE_TIMEOUT_SECONDS
from src.providers.codex_provider import DEFAULT_TIMEOUT_SECONDS as CODEX_TIMEOUT_SECONDS


def _tasks_for(departments: list[str]) -> list:
    mission = Mission(title="test", description="test", departments=departments)
    orchestrator = DepartmentOrchestrator()
    return orchestrator.create_tasks(mission)


class TestCodingDepartmentGetsAWiderBoundedOuterTimeout:
    """Requirement 9.A (bounded but realistic) proven at the mission/task
    creation boundary: only "coding" gets the wider budget, everyone else
    keeps the shared, unchanged constant."""

    def test_coding_task_timeout_covers_claude_code_plus_codex_worst_case(self):
        tasks = _tasks_for(["coding"])
        coding_task = next(t for t in tasks if t.agent == "coding")

        assert coding_task.timeout_seconds == CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS
        assert coding_task.timeout_seconds > CLAUDE_CODE_TIMEOUT_SECONDS + CODEX_TIMEOUT_SECONDS

    def test_coding_task_timeout_is_still_finite_and_bounded(self):
        tasks = _tasks_for(["coding"])
        coding_task = next(t for t in tasks if t.agent == "coding")

        assert coding_task.timeout_seconds < 1200.0  # generous but not unbounded

    def test_unrelated_departments_keep_the_shared_unchanged_timeout(self):
        tasks = _tasks_for(["github", "evaluation", "sandbox", "integration"])

        for task in tasks:
            assert task.timeout_seconds == DEPARTMENT_TASK_TIMEOUT_SECONDS
            assert task.timeout_seconds != CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS

    def test_coding_timeout_is_strictly_wider_than_the_shared_default(self):
        assert CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS > DEPARTMENT_TASK_TIMEOUT_SECONDS
