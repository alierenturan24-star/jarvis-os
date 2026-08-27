"""Regression tests for the SECOND real Swiss-Insider-Shorts mission run,
taken through the repaired capability-resolution runtime (see
``test_swiss_insider_mission_repair.py`` for the first round).

Real result (16% success, INCOMPLETE/BLOCKED):
  - media failed: "Görev zaman aşımına uğradı (75.0 sn).
    (son aşama: text_to_image_scene_1_of_4)" -- correct that it was a
    non-text failure, but no provider/model identity, and no bounded
    capability-specific fallback was attempted.
  - research claimed "Creen.ai" was free/accessible/suitable without that
    ever being verified as an operational capability.
  - research produced a topic titled with a stale "2024" year while the
    mission explicitly asked for "today's"/current information in 2026.
  - browser hit a Google "/sorry/" anti-bot page and it was not flagged.
  - GitHub was rate-limited; the resulting task looked like a normal
    (empty) completion instead of a distinguishable, bounded limitation.

Uses mocks only -- no live network/API/paid/YouTube/finance calls. Does
NOT add "Creen.ai" (or any other candidate from this research output) as a
provider; only strengthens the EXISTING boundary between "research prose"
and "verified operational capability".
"""

from __future__ import annotations

from src.core.task_plan import TaskPlan
from src.evaluation.evaluation_engine import EvaluationEngine
from src.github.errors import GitHubRateLimitError
from src.github.github_intelligence import GitHubIntelligence
from src.jobs.job_manager import JobManager
from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus
from src.mission.department_adapters import (
    EvaluationDepartmentAgent,
    GitHubDepartmentAgent,
    IntegrationDepartmentAgent,
    SandboxDepartmentAgent,
)
from src.mission.models import Mission, MissionType
from src.mission.recovery import _continue_capability_gaps, MissionRecoveryReport
from src.mission.report_builder import _research_section
from src.mission.target_resolver import Target, TargetKind


def _repository_target() -> Target:
    return Target(
        kind=TargetKind.REPOSITORY, owner="octo", repo="example",
        full_name="octo/example", url="https://github.com/octo/example",
    )


def _repo_task(agent: str) -> Task:
    return Task(title=f"[{agent}] x", agent=agent, metadata={"target": _repository_target()})


class TestGitHubRateLimitIsAnHonestBoundedLimitation:
    """Item 7: a rate limit must be represented as a bounded SOURCE
    limitation, not silently rendered as an empty-but-successful
    evaluation/sandbox/integration completion."""

    def test_github_department_reports_rate_limit_as_a_failure(self, monkeypatch):
        monkeypatch.setattr(
            GitHubIntelligence, "get_repository",
            lambda self, full_name, **k: (_ for _ in ()).throw(GitHubRateLimitError("rate limited")),
        )
        output = GitHubDepartmentAgent().execute(_repo_task("github"))
        assert output.casefold().startswith("hata")

    def test_evaluation_department_reports_rate_limit_as_a_failure(self, monkeypatch):
        monkeypatch.setattr(
            GitHubIntelligence, "get_repository",
            lambda self, full_name, **k: (_ for _ in ()).throw(GitHubRateLimitError("rate limited")),
        )
        output = EvaluationDepartmentAgent().execute(_repo_task("evaluation"))
        assert output.casefold().startswith("hata")

    def test_integration_department_reports_rate_limit_as_a_failure(self, monkeypatch):
        monkeypatch.setattr(
            GitHubIntelligence, "get_repository",
            lambda self, full_name, **k: (_ for _ in ()).throw(GitHubRateLimitError("rate limited")),
        )
        output = IntegrationDepartmentAgent().execute(_repo_task("integration"))
        assert output.casefold().startswith("hata")

    def test_sandbox_department_reports_rate_limit_as_a_failure(self, monkeypatch):
        monkeypatch.setattr(
            GitHubIntelligence, "get_repository",
            lambda self, full_name, **k: (_ for _ in ()).throw(GitHubRateLimitError("rate limited")),
        )
        output = SandboxDepartmentAgent().execute(_repo_task("sandbox"))
        assert output.casefold().startswith("hata")

    def test_rate_limited_github_task_cannot_masquerade_as_useful_completion(self, monkeypatch):
        # End-to-end through the SAME BaseAgent.run()/verify()/JobManager
        # path a real mission uses. JobManager itself always wraps a non-
        # raising handler call as an outer TaskResult(success=True) --
        # ``task.status`` stays COMPLETED by this codebase's OWN existing
        # design (see ``task_output_is_false_success`` docstring, Sprint
        # 43 FALSE SUCCESS RECOVERY: the same mechanism self-check/
        # recovery already use for every other department). What matters
        # is that the inner ``AgentResult`` is ``success=False`` AND the
        # false-success/recovery layer correctly recognizes this as a
        # real failure needing recovery -- not silently accepted as a
        # useful, complete result.
        from src.mission.failure_classification import FailureClass, classify_failure
        from src.mission.recovery import _needs_recovery
        from src.strategy.execution_planner import task_output_is_false_success

        monkeypatch.setattr(
            GitHubIntelligence, "get_repository",
            lambda self, full_name, **k: (_ for _ in ()).throw(GitHubRateLimitError("rate limited")),
        )
        agent = GitHubDepartmentAgent()
        task = _repo_task("github")
        task.handler = agent.to_handler()  # the REAL wiring (department_adapters.py), not execute() directly
        JobManager().run_task(task)

        assert task.result.output.success is False  # the AgentResult itself is honest
        assert task_output_is_false_success(task) is True
        assert classify_failure(str(task.result.output)) == FailureClass.RATE_LIMIT
        assert _needs_recovery(task) is True

    def test_not_found_repository_is_still_a_normal_honest_empty_result(self, monkeypatch):
        # Regression guard: a GENUINE "repo doesn't exist" must NOT be
        # reclassified as a failure -- only the rate-limit subclass is.
        from src.github.errors import GitHubIntelligenceError
        monkeypatch.setattr(
            GitHubIntelligence, "get_repository",
            lambda self, full_name, **k: (_ for _ in ()).throw(GitHubIntelligenceError("not found")),
        )
        output = GitHubDepartmentAgent().execute(_repo_task("github"))
        assert not output.casefold().startswith("hata")


class TestResearchClaimsCannotSelfPromoteToCapability:
    """Items 3/4: a research task's free-text output claiming a tool is
    "free"/"accessible"/"suitable" (e.g. the real report's "Creen.ai")
    must never, by itself, become an entry in ``mission.capability_
    candidates`` or an operational capability -- and the report must make
    the "unverified claim" boundary explicit."""

    def test_research_output_never_enters_the_candidate_pool(self):
        research_task = Task(title="[research] x", agent="research", handler=lambda t: "ok")
        research_task.status = TaskStatus.COMPLETED
        research_task.result = TaskResult(
            success=True,
            output=(
                "Creen.ai is a completely free, accessible AI video generation tool, "
                "perfectly suitable for this mission's needs."
            ),
        )
        # ResearchAgent never writes task.metadata["report"] -- confirmed
        # structurally, not just asserted here.
        assert "report" not in research_task.metadata

        plan = TaskPlan(goal="t")
        plan.add_task(research_task)
        mission = Mission(title="t", goal="t", mission_type=MissionType.YOUTUBE)
        mission.tasks = [research_task]
        mission.capability_gaps = ("media_artifact",)

        class _EmptyCollector:
            def collect(self, **kwargs):
                return []

        report = MissionRecoveryReport(goal=mission.goal)
        _continue_capability_gaps(
            mission, plan, report,
            evolution_collector=_EmptyCollector(), job_manager=JobManager(),
        )

        assert mission.capability_candidates == []
        assert "creen" not in " ".join(mission.current_capabilities).casefold()

    def test_research_section_carries_an_unverified_claim_disclaimer(self):
        task = Task(title="[research] x", agent="research", handler=lambda t: "ok")
        task.status = TaskStatus.COMPLETED
        task.result = TaskResult(
            success=True,
            output="Creen.ai is free and accessible.",
        )
        section = _research_section(task)
        assert "DOĞRULANMAMIŞ" in section
        assert "Creen.ai" in section  # the raw research text is still shown, just labeled
