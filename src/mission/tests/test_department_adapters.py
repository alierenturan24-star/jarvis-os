from __future__ import annotations

from src.agents.base_agent import BaseAgent
from src.evaluation.evaluation_engine import EvaluationEngine
from src.github.github_intelligence import GitHubIntelligence
from src.github.models import RepoData
from src.integration.integration_planner import IntegrationPlanner
from src.integration.models import IntegrationPlan
from src.jobs.task import Task
from src.jobs.task_status import TaskStatus
from src.mission.department_adapters import (
    DepartmentAdapterRegistry,
    EvaluationDepartmentAgent,
    GitHubDepartmentAgent,
    IntegrationDepartmentAgent,
    SandboxDepartmentAgent,
    resolve_search_category,
)
from src.mission.mission_engine import MissionEngine
from src.sandbox.models import SandboxResult, SandboxStatus
from src.sandbox.sandbox_manager import SandboxManager

# Bu paket, network/git-clone içeren gerçek çağrıları GitHubIntelligence
# ve SandboxManager'ın SINIF SEVİYESİNDE (monkeypatch ile) sahteleyerek
# test eder: EvaluationEngine ve IntegrationPlanner'ın kendisi saf/yerel
# mantık olduğu için (ağ çağrısı yapmazlar) GERÇEK haliyle çalışmaya
# devam eder -- yalnızca "hangi gerçek metot çağrıldı" gözlemlenir.


def _repo(name: str = "octocat/sample-agent", stars: int = 999) -> RepoData:
    return RepoData(
        name=name.split("/")[-1],
        full_name=name,
        url=f"https://github.com/{name}",
        description="A sample AI agent repo used for adapter tests.",
        stars=stars,
        forks=10,
        license="mit",
        last_update="2026-01-01T00:00:00Z",
        language="Python",
        category="ai agent",
        open_issues=1,
        archived=False,
        contributors_count=5,
    )


class TestResolveSearchCategory:
    def test_falls_back_to_ai_agent_for_turkish_free_text(self):
        assert resolve_search_category("Jarvis'i geliştir.") == "ai agent"

    def test_matches_a_supported_category_when_present_in_text(self):
        assert resolve_search_category("bana bir mcp server bul") == "mcp server"


# --- github: GitHubIntelligence gerçekten çağrılıyor mu -----------------------


class TestGitHubDepartmentAgentCallsRealClass:
    def test_search_is_invoked_on_real_github_intelligence(self, monkeypatch):
        calls = {}

        def fake_search(self, category, max_results=10, min_stars=0, fetch_readme=False):
            calls["category"] = category
            calls["max_results"] = max_results
            return [_repo()]

        monkeypatch.setattr(GitHubIntelligence, "search", fake_search)

        agent = GitHubDepartmentAgent()  # gerçek GitHubIntelligence örneği
        assert isinstance(agent.intelligence, GitHubIntelligence)

        task = Task(title="t", agent="github", target="Jarvis'i geliştir.")
        output = agent.execute(task)

        assert calls["category"] == "ai agent"
        assert "octocat/sample-agent" in output

    def test_empty_search_result_reported_not_crashed(self, monkeypatch):
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [])

        agent = GitHubDepartmentAgent()
        output = agent.execute(Task(title="t", agent="github", target="Jarvis'i geliştir."))

        assert "bulunamadı" in output


# --- evaluation: EvaluationEngine gerçekten çalışıyor mu -----------------------


class TestEvaluationDepartmentAgentCallsRealClass:
    def test_evaluate_invoked_on_real_evaluation_engine_with_real_repo_data(self, monkeypatch):
        # Sprint 18: EvaluationDepartmentAgent artik her aday icin
        # GitHub->Evaluation->Sandbox->IntegrationPlanner AI Validation
        # Pipeline'inin tamamini calistiriyor -- Sandbox/Integration'in
        # agi/klonlamayi tetiklememesi icin mocklaniyor.
        repo = _repo()
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [repo])
        monkeypatch.setattr(
            SandboxManager, "run_pipeline",
            lambda self, url, evaluation, repo=None, **k: SandboxResult(
                repository_name=repo.full_name if repo else url, repository_url=url,
                status=SandboxStatus.READY_FOR_REVIEW, recommended_action="ok",
            ),
        )
        monkeypatch.setattr(SandboxManager, "cleanup", lambda self, result: result)

        calls = {}
        original_evaluate = EvaluationEngine.evaluate

        def spy_evaluate(self, repo_data):
            calls.setdefault("repos", []).append(repo_data)
            return original_evaluate(self, repo_data)

        monkeypatch.setattr(EvaluationEngine, "evaluate", spy_evaluate)

        agent = EvaluationDepartmentAgent()
        assert isinstance(agent.engine, EvaluationEngine)

        task = Task(title="t", agent="evaluation", target="Jarvis'i geliştir.")
        output = agent.execute(task)

        assert calls["repos"] == [repo]
        assert repo.name in output
        assert "/100" in output

        candidate = task.metadata["report"]["candidates"][0]
        assert candidate["repo"] is repo
        assert candidate["sandbox_verdict"] == "PASS"
        assert candidate["integration_plan"] is not None


# --- sandbox: SandboxManager gerçekten çağrılıyor mu ---------------------------


class TestSandboxDepartmentAgentCallsRealClass:
    def test_run_pipeline_and_cleanup_invoked_on_real_sandbox_manager(self, monkeypatch):
        repo = _repo()
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [repo])

        pipeline_calls = {}

        def fake_run_pipeline(self, repository_url, evaluation, repo=None, **kwargs):
            pipeline_calls["repository_url"] = repository_url
            pipeline_calls["evaluation"] = evaluation
            return SandboxResult(
                repository_name=repo.full_name if repo else repository_url,
                repository_url=repository_url,
                status=SandboxStatus.READY_FOR_REVIEW,
                recommended_action="test ok",
            )

        cleanup_calls = []
        monkeypatch.setattr(SandboxManager, "run_pipeline", fake_run_pipeline)
        monkeypatch.setattr(SandboxManager, "cleanup", lambda self, result: cleanup_calls.append(result))

        agent = SandboxDepartmentAgent()
        assert isinstance(agent.manager, SandboxManager)

        output = agent.execute(Task(title="t", agent="sandbox", target="Jarvis'i geliştir."))

        assert pipeline_calls["repository_url"] == repo.url
        assert len(cleanup_calls) == 1  # sandbox dizini gerçekten temizlendi
        assert "ready_for_review" in output


# --- integration: IntegrationPlanner gerçekten çalışıyor mu --------------------


class TestIntegrationDepartmentAgentCallsRealClass:
    def test_analyze_invoked_on_real_integration_planner(self, monkeypatch):
        repo = _repo()
        sandbox_result = SandboxResult(
            repository_name=repo.full_name,
            repository_url=repo.url,
            status=SandboxStatus.READY_FOR_REVIEW,
        )

        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [repo])
        monkeypatch.setattr(SandboxManager, "run_pipeline", lambda self, *a, **k: sandbox_result)
        monkeypatch.setattr(SandboxManager, "cleanup", lambda self, result: result)

        calls = {}

        def fake_analyze(self, sandbox_res, evaluation):
            calls["sandbox_result"] = sandbox_res
            calls["evaluation"] = evaluation
            return IntegrationPlan(
                repository_name=repo.full_name,
                repository_url=repo.url,
                target_module="src/agents",
                target_package="src/agents",
                integration_strategy="test",
                estimated_files=1,
                estimated_changes=1,
                estimated_risk="LOW",
                breaking_change_probability=0.0,
                summary="ok-summary",
            )

        monkeypatch.setattr(IntegrationPlanner, "analyze", fake_analyze)

        agent = IntegrationDepartmentAgent()
        assert isinstance(agent.planner, IntegrationPlanner)

        output = agent.execute(Task(title="t", agent="integration", target="Jarvis'i geliştir."))

        assert calls["sandbox_result"] is sandbox_result
        assert "ok-summary" in output


# --- research/finance/browser: mevcut ajanlar YENİDEN kullanılıyor mu ---------


class TestRegistryReusesExistingAgentsNoDuplicateSystem:
    def test_research_finance_browser_resolve_to_existing_agent_classes(self):
        registry = DepartmentAdapterRegistry()

        for department, expected_class_name in (
            ("research", "ResearchAgent"),
            ("finance", "FinanceAgent"),
            ("browser", "BrowserAgent"),
        ):
            handler = registry.resolve(department)
            assert handler is not None
            assert type(handler.__self__).__name__ == expected_class_name
            assert isinstance(handler.__self__, BaseAgent)

    def test_still_unconnected_departments_resolve_to_none(self):
        registry = DepartmentAdapterRegistry()
        for department in ("automation", "media", "social_media", "security", "learning", "coding"):
            assert registry.resolve(department) is None


# --- Mission -> TaskPlan -> Execution -> Gerçek handler -> Sonuç ---------------


class TestMissionExecutionReachesRealHandlers:
    def test_develop_jarvis_tasks_get_real_handlers_not_missing_handler_error(self, monkeypatch):
        repo = _repo()
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [repo])
        monkeypatch.setattr(
            SandboxManager,
            "run_pipeline",
            lambda self, url, evaluation, repo=None, **k: SandboxResult(
                repository_name=repo.full_name if repo else url,
                repository_url=url,
                status=SandboxStatus.READY_FOR_REVIEW,
                recommended_action="ok",
            ),
        )
        monkeypatch.setattr(SandboxManager, "cleanup", lambda self, result: result)

        engine = MissionEngine()
        mission = engine.create_mission("Jarvis'i geliştir.")
        plan = engine.build_task_plan(mission)

        # github/evaluation/sandbox/integration departmanlarının hepsi
        # artık gerçek bir handler'a sahip olmalı (Sprint 14'teki gibi
        # None DEĞİL).
        for task in plan.all_tasks():
            assert task.handler is not None, f"{task.agent} için handler bağlanmadı"

        report = engine.orchestrator.dispatch(mission, plan)

        for task in plan.all_tasks():
            assert task.error != "Görev için handler tanımlı değil."
            assert task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)

        assert any(task.status == TaskStatus.COMPLETED for task in plan.all_tasks())
        assert report.plan is plan
