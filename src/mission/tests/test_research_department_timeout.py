from __future__ import annotations

from src.config.settings import Settings, _env_float
from src.mission.department_orchestrator import (
    DEPARTMENT_TASK_TIMEOUT_SECONDS,
    RESEARCH_DEPARTMENT_TASK_TIMEOUT_SECONDS,
    DepartmentOrchestrator,
)
from src.mission.models import Mission
from src.research.collector import MAX_SEARCH_STEPS

# Sprint: research/production pipeline audit -- a real Swiss Insider mission
# run failed with "Task timed out (20.0 sec)." during research. Root cause
# traced across the whole timeout hierarchy:
#   - inner: WebSearchTool/ResearchCollector per-search-call timeout
#     (Settings.RESEARCH_PROVIDER_TIMEOUT_SECONDS, was a bare 15.0 constant)
#   - outer: the department's own task timeout (was the SAME shared
#     DEPARTMENT_TASK_TIMEOUT_SECONDS=75s every non-coding department gets,
#     never sized to research's own real worst-case: up to MAX_SEARCH_STEPS
#     sequential searches + one summarization LLM call)
#   - recovery: mission/recovery.py's same-method retry step (see
#     test_recovery.py) unconditionally shrank ANY timeout-classified retry
#     to a flat 20s -- smaller than even ONE inner search call's own
#     timeout, which is the literal "(20.0 sec)" in the real failure.
# These tests prove the SAME safe invariant already used for the coding
# department (see test_coding_department_timeout.py): inner operation
# timeout < outer department timeout, by construction, and configurable/
# bounded like Settings.CLAUDE_CODE_TIMEOUT_SECONDS.


def _tasks_for(departments: list[str]) -> list:
    mission = Mission(title="test", description="test", departments=departments)
    orchestrator = DepartmentOrchestrator()
    return orchestrator.create_tasks(mission)


# Test A: legitimate research may run longer than 20 seconds.
class TestA_ResearchMayLegitimatelyRunLongerThan20Seconds:
    def test_research_task_timeout_is_the_dedicated_research_budget(self):
        tasks = _tasks_for(["research"])
        research_task = next(t for t in tasks if t.agent == "research")

        assert research_task.timeout_seconds == RESEARCH_DEPARTMENT_TASK_TIMEOUT_SECONDS
        assert research_task.timeout_seconds > 20.0

    def test_research_timeout_is_still_finite_and_bounded(self):
        tasks = _tasks_for(["research"])
        research_task = next(t for t in tasks if t.agent == "research")

        assert research_task.timeout_seconds < 1200.0  # generous but not unbounded


# Test B: the outer task timeout cannot kill research before its inner
# provider timeout -- outer budget covers the REAL worst-case inner sum.
class TestB_OuterTimeoutCannotKillResearchBeforeInnerProviderTimeout:
    def test_outer_research_budget_covers_worst_case_sequential_searches(self):
        worst_case_search_time = Settings.RESEARCH_PROVIDER_TIMEOUT_SECONDS * MAX_SEARCH_STEPS
        assert RESEARCH_DEPARTMENT_TASK_TIMEOUT_SECONDS > worst_case_search_time

    def test_research_timeout_is_strictly_wider_than_the_shared_default(self):
        # SAME invariant coding already proves (test_coding_department_timeout.py):
        # a department with real provider-backed latency needs MORE than the
        # generic shared default, never less.
        assert RESEARCH_DEPARTMENT_TASK_TIMEOUT_SECONDS > DEPARTMENT_TASK_TIMEOUT_SECONDS


# Test C: malformed timeout configuration fails safely (never raises, never
# produces an unbounded/invalid wait) -- same _env_float contract already
# proven generically in src/config/tests/test_env_float.py, exercised here
# with research's OWN exact name/default/bounds.
class TestC_MalformedResearchTimeoutConfigFailsSafely:
    def test_non_numeric_research_provider_timeout_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROVIDER_TIMEOUT_SECONDS", "not-a-number")
        assert _env_float("RESEARCH_PROVIDER_TIMEOUT_SECONDS", 15.0, minimum=5.0, maximum=45.0) == 15.0

    def test_absurdly_large_research_provider_timeout_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROVIDER_TIMEOUT_SECONDS", "999999")
        assert _env_float("RESEARCH_PROVIDER_TIMEOUT_SECONDS", 15.0, minimum=5.0, maximum=45.0) == 15.0

    def test_malformed_recovery_retry_timeout_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("RECOVERY_SAME_METHOD_RETRY_TIMEOUT_SECONDS", "abc")
        assert _env_float("RECOVERY_SAME_METHOD_RETRY_TIMEOUT_SECONDS", 300.0, minimum=15.0, maximum=600.0) == 300.0

    def test_resolved_research_settings_are_within_their_own_documented_bounds(self):
        assert 5.0 <= Settings.RESEARCH_PROVIDER_TIMEOUT_SECONDS <= 45.0
        assert 15.0 <= Settings.RECOVERY_SAME_METHOD_RETRY_TIMEOUT_SECONDS <= 600.0


# Test D: unrelated departments retain their existing timeout behavior --
# only "coding" and "research" get a dedicated outer budget; everyone else
# keeps the shared, unchanged constant (same proof pattern as
# test_coding_department_timeout.py's own Test D, extended to confirm
# research's new budget didn't leak into unrelated departments).
class TestD_UnrelatedDepartmentsRetainExistingTimeoutBehavior:
    def test_non_research_non_coding_departments_keep_the_shared_timeout(self):
        tasks = _tasks_for(["github", "evaluation", "sandbox", "integration", "browser"])

        for task in tasks:
            assert task.timeout_seconds == DEPARTMENT_TASK_TIMEOUT_SECONDS
            assert task.timeout_seconds != RESEARCH_DEPARTMENT_TASK_TIMEOUT_SECONDS

    def test_research_budget_is_distinct_from_and_does_not_replace_the_shared_default(self):
        assert RESEARCH_DEPARTMENT_TASK_TIMEOUT_SECONDS != DEPARTMENT_TASK_TIMEOUT_SECONDS
        tasks = _tasks_for(["media", "finance"])
        for task in tasks:
            # media/finance are provider-backed (see recovery.py
            # PROVIDER_BACKED_DEPARTMENTS) but not given a dedicated outer
            # budget by THIS fix -- they must still get the shared default,
            # unchanged.
            assert task.timeout_seconds == DEPARTMENT_TASK_TIMEOUT_SECONDS
