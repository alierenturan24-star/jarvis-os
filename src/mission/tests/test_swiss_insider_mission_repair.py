"""Regression tests for the real Swiss-Insider-Shorts mission failure.

The mission asked JARVIS to "Research today's highest-potential Swiss
Insider YouTube Shorts opportunity in the Swiss market." (a pure DOMAIN/
CONTENT research goal). The real run went to ~23% and BLOCKED because:

  ROOT CAUSE A: content research and capability/acquisition research were
    conflated -- GitHub/Evaluation/Sandbox/Integration were dispatched for
    every YouTube mission regardless of any actual tool/repo need.
  ROOT CAUSE B: media capability failures (text_to_image/image_to_video)
    were "recovered" by swapping the TEXT provider (ollama/gemini/
    claude_code/codex) -- none of those advertise those capabilities.
  ROOT CAUSE C: discovered capability candidates vanished silently between
    stages (3 found -> 1 evaluated -> 0 sandboxed -> 0) with no evidence.
  A target-extraction bug turned a stray hyphenated list/range fragment
    (the real report showed "1-2") into an exact-name GitHub search,
    matching an unrelated repository (the real report showed
    "Bongetis/1-2").
  Media production hit a flat "timeout (75.0 sn)" with no indication of
    which internal stage was running.
  A YouTube-only mission's report falsely included "Finance learning
    persisted: ..." (the "learning" department only ever resolved to the
    finance-only ``FinanceLearningAgent``).

These tests reproduce each bug against the FIXED code (all should now
pass) using mocks only -- no live network/API/paid/YouTube/finance calls.

``HISTORICAL_BAD_TARGET``/``HISTORICAL_BAD_REPO`` below are a SANITIZED
regression fixture: the exact bad strings from the real failed run, used
ONLY as comparison values in assertions (never special-cased by
production code).
"""

from __future__ import annotations

from types import SimpleNamespace

from src.core.task_plan import TaskPlan
from src.evaluation.evaluation_engine import EvaluationEngine
from src.evaluation.models import RepoEvaluation
from src.github.github_intelligence import GitHubIntelligence
from src.github.models import RepoData
from src.jobs.job_manager import JobManager
from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus
from src.mission.department_adapters import DepartmentAdapterRegistry
from src.mission.department_orchestrator import DEPARTMENT_TASK_TIMEOUT_SECONDS, DepartmentOrchestrator
from src.mission.models import Mission, MissionType
from src.mission.recovery import (
    CANDIDATE_INTEGRATION_APPROVAL_REQUIRED,
    CANDIDATE_REJECTED_RELEVANCE,
    CANDIDATE_UNRESOLVED,
    MissionRecoveryReport,
    RecoveryAttemptHistory,
    RecoveryStep,
    _continue_capability_gaps,
    discover_for_goal,
    recover_mission,
    recover_task,
)
from src.mission.report_builder import _task_note
from src.mission.target_resolver import TargetKind, TargetResolver
from src.providers.provider_manager import ProviderManager
from src.sandbox.models import SandboxResult, SandboxStatus
from src.sandbox.sandbox_manager import SandboxManager

REAL_MISSION_GOAL = (
    "Research today's highest-potential Swiss Insider YouTube Shorts opportunity "
    "in the Swiss market."
)

# Sanitized regression fixture -- SEE MODULE DOCSTRING. Never used to drive
# production logic, only as a "must never reproduce this" comparison value.
HISTORICAL_BAD_TARGET = "1-2"
HISTORICAL_BAD_REPO = "Bongetis/1-2"


class _FakeProvider:
    def __init__(self, available: bool = True) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available


def _provider_manager(**availability: bool) -> ProviderManager:
    manager = ProviderManager()
    for name, available in availability.items():
        manager._providers[name] = _FakeProvider(available=available)
    return manager


def _mission(mission_type: MissionType = MissionType.YOUTUBE, goal: str = REAL_MISSION_GOAL) -> Mission:
    return Mission(title=goal, description=goal, goal=goal, mission_type=mission_type)


def _repo(full_name: str = "octocat/example") -> RepoData:
    return RepoData(
        name=full_name.split("/")[-1], full_name=full_name,
        url=f"https://github.com/{full_name}", description="test",
        stars=10, forks=1, license="MIT", last_update="2026-01-01T00:00:00Z",
        language="Python", category="ai agent",
    )


def _evaluation(**overrides) -> RepoEvaluation:
    base = dict(
        name="example", url="https://github.com/octocat/example",
        overall_score=80.0, architecture_score=80.0, activity_score=80.0,
        community_score=80.0, license_score=80.0, security_score=80.0,
        compatibility_score=80.0, maintenance_score=80.0, relevance_score=80.0,
        recommendation="ÖNER", suitable_for_jarvis=True, target_module="media",
        integration_difficulty="LOW", risk_level="LOW",
    )
    base.update(overrides)
    return RepoEvaluation(**base)


def _empty_collector():
    class _Collector:
        def collect(self, **kwargs):
            return []

    return _Collector()


def _run_continue_capability_gaps(mission: Mission, plan: TaskPlan) -> MissionRecoveryReport:
    """Exercises the candidate-discovery/evaluation/sandbox/integration
    continuation directly (same function ``recover_mission`` calls) --
    avoids depending on ``recover_mission``'s unrelated "does this mission
    need recovery at all" gate (failed tasks / completion-requirement
    evaluation), which is out of scope for these candidate-lifecycle
    tests."""

    report = MissionRecoveryReport(goal=mission.goal or mission.title)
    _continue_capability_gaps(
        mission, plan, report, evolution_collector=_empty_collector(), job_manager=JobManager(),
    )
    return report


# --- TEST A: content goal does not dispatch GitHub acquisition research ---------


class TestRootCauseA_ContentVsCapabilityResearch:
    def test_swiss_insider_style_goal_does_not_dispatch_github_acquisition_chain(self):
        departments = DepartmentOrchestrator().select_departments(REAL_MISSION_GOAL)
        assert "github" not in departments
        assert "evaluation" not in departments
        assert "sandbox" not in departments
        assert "integration" not in departments
        # The content-research/production departments remain intact.
        assert "research" in departments
        assert "media" in departments

    def test_explicit_repo_ask_still_dispatches_github(self):
        # A GENUINE acquisition/tool need must still work exactly as before.
        departments = DepartmentOrchestrator().select_departments(
            "Find the best open source repo for YouTube automation."
        )
        assert "github" in departments


# --- TEST D/E: target extraction cannot be hijacked into a GitHub lookup --------


class TestRootCauseD_E_TargetHijack:
    def test_numeric_range_hyphen_is_never_treated_as_a_project_name(self):
        # Sanitized regression fixture: the real report's target became
        # "1-2" (a rank/list-range fragment, not a project name).
        target = TargetResolver().resolve(
            "Top 1-2 opportunities were identified after reviewing the Swiss market this week."
        )
        assert target.requested_name != HISTORICAL_BAD_TARGET

    def test_content_goal_falls_through_to_free_text_not_github_category(self):
        target = TargetResolver().resolve(REAL_MISSION_GOAL, mission_type=MissionType.YOUTUBE)
        assert target.kind == TargetKind.FREE_TEXT
        assert target.category_hint is None

    def test_acquisition_signal_still_resolves_youtube_github_category(self):
        target = TargetResolver().resolve(
            "Find a free open source tool/provider for YouTube automation.",
            mission_type=MissionType.YOUTUBE,
        )
        assert target.kind == TargetKind.CATEGORY
        assert target.category_hint == "youtube automation"

    def test_irrelevant_repo_cannot_replace_content_research_target(self, monkeypatch):
        # Even if GitHub search were somehow invoked, a fixed unrelated repo
        # name must never be substituted as the mission's real target/result.
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [_repo("Bongetis/1-2")])
        target = TargetResolver().resolve(REAL_MISSION_GOAL, mission_type=MissionType.YOUTUBE)
        # FREE_TEXT target: GitHubIntelligence.search is never even reached
        # via the normal department dispatch for this goal (see TEST A) --
        # this only pins that resolution itself does not manufacture a
        # github-category target that could reach HISTORICAL_BAD_REPO.
        assert target.category_hint is None


# --- TEST B/C: capability discovery is scoped, original goal is preserved ------


class TestRootCauseB_C_CapabilityDiscoveryFocus:
    def test_discovery_focus_is_capability_specific_not_the_full_mission_text(self):
        class _Collector:
            def collect(self, focus="", broad=True, **kwargs):
                return [{"title": "cand", "url": "https://example.com/cand"}]

        task = Task(title="capability discovery", agent="capability", handler=None)
        mission = _mission()
        mission.capability_gaps = ("media_artifact",)

        outcome = discover_for_goal(mission, task, _Collector())

        assert outcome.ran is True
        assert outcome.focus != mission.goal
        assert "media_artifact" in outcome.focus
        # The original goal text is untouched by scoping the discovery query.
        assert mission.goal == REAL_MISSION_GOAL

    def test_original_goal_preserved_through_recovery(self):
        task = Task(title="[media] x", agent="media", handler=lambda t: "ok")
        task.status = TaskStatus.FAILED
        task.error = "Görev zaman aşımına uğradı (75.0 sn)."
        plan = TaskPlan(goal="t")
        plan.add_task(task)
        mission = _mission()
        mission.tasks = [task]
        mission.capability_gaps = ("media_artifact",)

        recover_mission(mission, plan, evolution_collector=_empty_collector())

        assert mission.goal == REAL_MISSION_GOAL


# --- TEST F/G/H: provider fallback vs. capability fallback ----------------------


class TestRootCauseB_MediaCapabilityAwareFallback:
    def test_text_planning_failure_falls_back_among_compatible_text_providers(self):
        calls: list[str] = []

        def handler(task: Task):
            provider = task.metadata.get("preferred_ai_provider")
            calls.append(provider)
            task.metadata["last_stage"] = "planning"
            if provider == "gemini":
                return "ok"
            raise RuntimeError("Ollama zaman aşımına uğradı.")

        task = Task(
            title="t", agent="media", handler=handler,
            metadata={"preferred_ai_provider": "ollama", "last_stage": "planning"},
        )
        task.status = TaskStatus.FAILED
        task.error = "Ollama zaman aşımına uğradı."

        manager = _provider_manager(ollama=True, gemini=True)
        attempts = recover_task(
            task, _mission(), provider_manager=manager,
            job_manager=JobManager(), history=RecoveryAttemptHistory(),
        )

        assert any(a.provider_tried == "gemini" and a.succeeded for a in attempts)

    def test_text_to_image_failure_does_not_fall_back_to_text_providers(self):
        task = Task(
            title="t", agent="media", handler=lambda t: "unused",
            metadata={"preferred_ai_provider": "ollama", "last_stage": "text_to_image_scene_1_of_4"},
        )
        task.status = TaskStatus.FAILED
        task.error = "Görev zaman aşımına uğradı (75.0 sn)."

        manager = _provider_manager(ollama=True, gemini=True, codex=True, claude_code=True)
        attempts = recover_task(
            task, _mission(), provider_manager=manager,
            job_manager=JobManager(), history=RecoveryAttemptHistory(),
        )

        # A bounded (1x) capability-specific retry now runs (real-mission
        # follow-up evidence, item 2) -- but it is NEVER a text-provider
        # swap: ``provider_tried`` is the capability-cooldown marker, never
        # one of the text providers.
        assert len(attempts) == 1
        assert attempts[0].step == RecoveryStep.NON_TEXT_MEDIA_CAPABILITY_GAP
        assert not any(
            a.provider_tried in {"ollama", "gemini", "codex", "claude_code"} for a in attempts
        )

    def test_image_to_video_failure_only_considers_compatible_routes(self):
        task = Task(
            title="t", agent="media", handler=lambda t: "unused",
            metadata={"preferred_ai_provider": "ollama", "last_stage": "image_to_video_scene_2_of_4"},
        )
        task.status = TaskStatus.FAILED
        task.error = "Görev zaman aşımına uğradı (75.0 sn)."

        manager = _provider_manager(ollama=True, gemini=True)
        attempts = recover_task(
            task, _mission(), provider_manager=manager,
            job_manager=JobManager(), history=RecoveryAttemptHistory(),
        )

        assert len(attempts) == 1
        assert attempts[0].step == RecoveryStep.NON_TEXT_MEDIA_CAPABILITY_GAP

    def test_legacy_media_task_without_stage_evidence_fails_open_to_old_behavior(self):
        # Tasks/tests predating stage tracking must not be silently blocked.
        calls: list[str] = []

        def handler(task: Task):
            provider = task.metadata.get("preferred_ai_provider")
            calls.append(provider)
            if provider == "gemini":
                return "ok"
            raise RuntimeError("Ollama zaman aşımına uğradı.")

        task = Task(
            title="t", agent="media", handler=handler,
            metadata={"preferred_ai_provider": "ollama"},
        )
        task.status = TaskStatus.FAILED
        task.error = "Ollama zaman aşımına uğradı."

        manager = _provider_manager(ollama=True, gemini=True)
        attempts = recover_task(
            task, _mission(), provider_manager=manager,
            job_manager=JobManager(), history=RecoveryAttemptHistory(),
        )
        assert any(a.provider_tried == "gemini" and a.succeeded for a in attempts)


class TestBoundedCapabilitySpecificMediaFallback:
    """Real-mission follow-up evidence (item 2): recovery correctly SKIPPED
    the generic text-provider ladder for a text_to_image timeout, but never
    attempted any capability-specific fallback either. A bounded (1x) retry
    now runs, reusing the EXISTING provider health/cooldown mechanism
    (``src.media.provider_selection.provider_health`` /
    ``src.providers.execution_history.ProviderExecutionHistory``) so the
    stalled provider is deprioritized on retry -- never a new provider."""

    def test_stalled_provider_is_cooled_down_and_a_bounded_retry_runs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from src.media.capability_model import TEXT_TO_IMAGE
        from src.media.provider_selection import provider_health
        from src.mission.recovery import _MEDIA_CAPABILITY_RETRY_MARKER
        from src.providers.execution_history import ProviderExecutionHistory

        # 2 prior REAL failures already on record for "nvidia" -- the
        # cooldown mechanism trips at 3 consecutive failures.
        history_store = ProviderExecutionHistory()
        for _ in range(2):
            history_store.record(
                task_type=TEXT_TO_IMAGE, provider="nvidia", success=False,
                fallback_used=False, duration_seconds=1.0,
            )
        assert provider_health("nvidia", TEXT_TO_IMAGE, ProviderExecutionHistory()).status == "HEALTHY"

        calls: list[str] = []

        def handler(task: Task):
            calls.append("called")
            return "ok"

        task = Task(
            title="t", agent="media", handler=handler,
            metadata={
                "preferred_ai_provider": "ollama",
                "last_stage": "text_to_image_scene_1_via_nvidia/sdxl-turbo",
            },
        )
        task.status = TaskStatus.FAILED
        task.error = "Görev zaman aşımına uğradı (75.0 sn)."

        manager = _provider_manager(ollama=True)
        attempts = recover_task(
            task, _mission(), provider_manager=manager,
            job_manager=JobManager(), history=RecoveryAttemptHistory(),
        )

        assert len(calls) == 1  # the bounded (1x) retry actually ran the handler
        assert len(attempts) == 1
        assert attempts[0].step == RecoveryStep.NON_TEXT_MEDIA_CAPABILITY_GAP
        assert attempts[0].provider_tried == _MEDIA_CAPABILITY_RETRY_MARKER
        assert attempts[0].succeeded is True

        # The timeout is now recorded as nvidia's 3rd consecutive failure --
        # the EXISTING cooldown mechanism has genuinely learned from it.
        health = provider_health("nvidia", TEXT_TO_IMAGE, ProviderExecutionHistory())
        assert health.status == "COOLDOWN"

    def test_bounded_retry_only_ever_happens_once_per_task(self):
        task = Task(
            title="t", agent="media", handler=lambda t: "unused",
            metadata={"preferred_ai_provider": "ollama", "last_stage": "text_to_image_scene_1_of_4"},
        )
        task.status = TaskStatus.FAILED
        task.error = "Görev zaman aşımına uğradı (75.0 sn)."
        manager = _provider_manager(ollama=True)
        history = RecoveryAttemptHistory()

        first = recover_task(
            task, _mission(), provider_manager=manager, job_manager=JobManager(), history=history,
        )
        # Simulate: the task failed again on a later pass.
        task.status = TaskStatus.FAILED
        task.error = "Görev zaman aşımına uğradı (75.0 sn)."
        second = recover_task(
            task, _mission(), provider_manager=manager, job_manager=JobManager(), history=history,
        )

        assert len(first) == 1
        assert len(second) == 1
        assert "zaten tüketildi" in second[0].note

    def test_no_provider_identity_in_stage_is_a_safe_no_op_for_cooldown(self, tmp_path, monkeypatch):
        # A coarser/older stage marker (no "_via_provider/model" suffix)
        # must not crash the cooldown lookup -- it's simply skipped.
        monkeypatch.chdir(tmp_path)
        from src.mission.recovery import _cooldown_stalled_media_provider

        task = Task(title="t", agent="media", handler=lambda t: "ok",
                    metadata={"last_stage": "render"})
        _cooldown_stalled_media_provider(task)  # must not raise


# --- TEST I/J/L: candidate lifecycle is evidence-preserving ---------------------


class TestRootCauseC_CandidateLifecycle:
    def test_non_repository_candidate_is_never_sent_through_github_pipeline(self, monkeypatch):
        called = {"evaluate": False}
        monkeypatch.setattr(
            EvaluationEngine, "evaluate",
            lambda self, repo: called.__setitem__("evaluate", True) or _evaluation(),
        )

        task = Task(
            title="[github] x", agent="github", handler=lambda t: "ok",
            metadata={"report": {"candidates": [
                {"title": "remote-api-candidate", "url": "https://example.test/api"},
            ]}},
        )
        task.status = TaskStatus.COMPLETED
        task.result = TaskResult(success=True, output="ok")
        plan = TaskPlan(goal="t")
        plan.add_task(task)
        mission = _mission()
        mission.tasks = [task]
        mission.capability_gaps = ("media_artifact",)

        _run_continue_capability_gaps(mission, plan)

        assert len(mission.capability_candidates) == 1
        candidate = mission.capability_candidates[0]
        assert candidate["status"] == CANDIDATE_UNRESOLVED
        assert called["evaluate"] is False

    def test_low_relevance_repository_candidate_gets_rejected_relevance_status(self, monkeypatch):
        repo = _repo("octo/example")
        monkeypatch.setattr(GitHubIntelligence, "get_repository", lambda self, full_name, **k: repo)
        monkeypatch.setattr(
            EvaluationEngine, "evaluate",
            lambda self, r: _evaluation(
                suitable_for_jarvis=False, relevance_score=10.0, recommendation="REDDET - alakasız",
            ),
        )

        task = Task(
            title="[github] x", agent="github", handler=lambda t: "ok",
            metadata={"report": {"candidates": [
                {"title": "octo/example", "url": "https://github.com/octo/example"},
            ]}},
        )
        task.status = TaskStatus.COMPLETED
        task.result = TaskResult(success=True, output="ok")
        plan = TaskPlan(goal="t")
        plan.add_task(task)
        mission = _mission()
        mission.tasks = [task]
        mission.capability_gaps = ("media_artifact",)

        _run_continue_capability_gaps(mission, plan)

        candidate = mission.capability_candidates[0]
        assert candidate["status"] == CANDIDATE_REJECTED_RELEVANCE
        assert candidate["status_reason"]

    def test_repository_candidate_passing_sandbox_reaches_integration_approval_required(self, monkeypatch):
        repo = _repo("octo/good")
        monkeypatch.setattr(GitHubIntelligence, "get_repository", lambda self, full_name, **k: repo)
        monkeypatch.setattr(EvaluationEngine, "evaluate", lambda self, r: _evaluation())
        monkeypatch.setattr(
            SandboxManager, "run_pipeline",
            lambda self, url, evaluation, repo=None, **k: SandboxResult(
                repository_name=repo.full_name if repo else url, repository_url=url,
                status=SandboxStatus.READY_FOR_REVIEW, recommended_action="ok",
            ),
        )
        monkeypatch.setattr(SandboxManager, "cleanup", lambda self, result: result)

        task = Task(
            title="[github] x", agent="github", handler=lambda t: "ok",
            metadata={"report": {"candidates": [
                {"title": "octo/good", "url": "https://github.com/octo/good"},
            ]}},
        )
        task.status = TaskStatus.COMPLETED
        task.result = TaskResult(success=True, output="ok")
        plan = TaskPlan(goal="t")
        plan.add_task(task)
        mission = _mission()
        mission.tasks = [task]
        mission.capability_gaps = ("media_artifact",)

        _run_continue_capability_gaps(mission, plan)

        candidate = mission.capability_candidates[0]
        assert candidate["status"] == CANDIDATE_INTEGRATION_APPROVAL_REQUIRED

    def test_three_candidates_all_keep_a_terminal_status_none_silently_dropped(self, monkeypatch):
        # Sanitized regression fixture: the real report said "3 candidates
        # found -> Evaluation 1 -> Sandbox 0 -> ... 0" with no explanation
        # for the missing 2. All 3 must remain visible with a real status.
        monkeypatch.setattr(
            GitHubIntelligence, "get_repository",
            lambda self, full_name, **k: _repo(full_name),
        )
        monkeypatch.setattr(
            EvaluationEngine, "evaluate",
            lambda self, r: _evaluation(suitable_for_jarvis=False, relevance_score=5.0),
        )

        task = Task(
            title="[github] x", agent="github", handler=lambda t: "ok",
            metadata={"report": {"candidates": [
                {"title": "not-a-repo", "url": "https://example.test/api"},
                {"title": "octo/one", "url": "https://github.com/octo/one"},
                {"title": "octo/two", "url": "https://github.com/octo/two"},
            ]}},
        )
        task.status = TaskStatus.COMPLETED
        task.result = TaskResult(success=True, output="ok")
        plan = TaskPlan(goal="t")
        plan.add_task(task)
        mission = _mission()
        mission.tasks = [task]
        mission.capability_gaps = ("media_artifact",)

        _run_continue_capability_gaps(mission, plan)

        assert len(mission.capability_candidates) == 3
        assert all(c.get("status") for c in mission.capability_candidates)


# --- TEST P/Q: media timeout diagnostics ----------------------------------------


class TestMediaTimeoutDiagnostics:
    def test_task_note_surfaces_the_last_recorded_stage_on_timeout(self):
        task = Task(
            title="[media] x", agent="media", handler=lambda t: "ok",
            metadata={"last_stage": "text_to_image_scene_2_of_4"},
        )
        task.status = TaskStatus.FAILED
        task.error = "Görev zaman aşımına uğradı (75.0 sn)."

        note = _task_note(task)
        assert "text_to_image_scene_2_of_4" in note

    def test_task_note_has_no_stage_suffix_when_nothing_was_recorded(self):
        task = Task(title="[media] x", agent="media", handler=lambda t: "ok")
        task.status = TaskStatus.FAILED
        task.error = "Görev zaman aşımına uğradı (75.0 sn)."

        note = _task_note(task)
        assert "son aşama" not in note

    def test_media_manager_plan_marks_planning_stage_before_the_llm_call(self, monkeypatch):
        from src.media.manager import MediaManager

        manager = MediaManager()
        sink: dict = {}
        monkeypatch.setattr(
            manager.router.manager, "route_and_generate",
            lambda **k: SimpleNamespace(
                output="LLM yanıt vermedi.", fallback_used=False,
                chosen_provider="ollama", provider_used="ollama",
            ),
        )
        manager.plan("test topic", stage_sink=sink)
        assert sink.get("last_stage") == "planning"

    def test_department_task_timeout_stays_bounded(self):
        # The 75s budget itself is unchanged by this repair -- ROOT CAUSE was
        # missing stage evidence, not an under-sized timeout (see report).
        assert 0 < DEPARTMENT_TASK_TIMEOUT_SECONDS < 600


# --- TEST R/S: Finance learning must not leak into YouTube reports -------------


class TestFinanceLearningDomainLeak:
    def test_youtube_mission_with_learning_word_does_not_dispatch_finance_learning(self):
        goal = "Produce a new YouTube Shorts learning video about space history; use no prior memory."
        departments = DepartmentOrchestrator().select_departments(goal)
        assert "learning" not in departments

    def test_finance_mission_with_learning_word_still_dispatches_finance_learning(self):
        goal = "Finance stratejisi için backtest ve learning döngüsünü çalıştır."
        departments = DepartmentOrchestrator().select_departments(goal)
        assert "finance" in departments
        assert "learning" in departments

    def test_finance_learning_handler_still_resolves_for_genuine_finance_missions(self):
        handler = DepartmentAdapterRegistry().resolve("learning")
        assert handler is not None
        assert type(handler.__self__).__name__ == "FinanceLearningAgent"

    def test_generic_educational_youtube_request_does_not_trigger_finance_learning(self):
        # Turkish "öğretici" wording could match the "learning" Department's
        # own keywords via the generic enrichment scan -- must still be
        # blocked for a non-finance mission.
        goal = "Çocuklar için öğretici bir YouTube Shorts videosu üret."
        departments = DepartmentOrchestrator().select_departments(goal)
        assert "learning" not in departments
