from __future__ import annotations

from src.core.ceo import CEO
from src.evaluation.models import RepoEvaluation
from src.github.github_intelligence import GitHubIntelligence
from src.github.models import RepoData
from src.integration.integration_planner import IntegrationPlanner
from src.integration.models import IntegrationPlan
from src.jobs.task import Task
from src.jobs.task_status import TaskStatus
from src.mission.mission_engine import MissionEngine
from src.mission.models import Mission, MissionType
from src.mission.report_builder import build_ceo_report
from src.sandbox.models import SandboxResult, SandboxStatus
from src.sandbox.sandbox_manager import SandboxManager


def _repo(name: str = "octocat/sample-agent", stars: int = 4200) -> RepoData:
    return RepoData(
        name=name.split("/")[-1],
        full_name=name,
        url=f"https://github.com/{name}",
        description="A sample AI agent repo used for report builder tests.",
        stars=stars,
        forks=10,
        license="mit",
        last_update="2026-01-01T00:00:00Z",
        language="Python",
        category="ai agent",
        open_issues=1,
        archived=False,
        contributors_count=25,
    )


def _mission_with_task(agent: str, *, status=TaskStatus.COMPLETED, handler=lambda t: "ok", metadata=None) -> Mission:
    mission = Mission(title="test mission", mission_type=MissionType.CODE, departments=[agent])
    task = Task(title=f"[{agent}] test", agent=agent, target="test", handler=handler, metadata=metadata or {})
    task.status = status
    mission.tasks = [task]
    return mission


class TestSectionsHandleMissingOrIncompleteDepartments:
    def test_department_not_selected_shows_not_selected_note(self):
        mission = Mission(title="t", mission_type=MissionType.RESEARCH, departments=["research"])
        mission.tasks = []
        report = build_ceo_report(mission)
        assert "bu mission'da bu departman seçilmedi" in report

    def test_unconnected_department_shows_no_handler_note(self):
        mission = _mission_with_task("automation", handler=None)
        report = build_ceo_report(mission)
        assert "Bağlı değil" in report

    def test_failed_task_shows_status_and_error(self):
        mission = _mission_with_task("github", status=TaskStatus.FAILED)
        mission.tasks[0].error = "boom"
        report = build_ceo_report(mission)
        assert "Tamamlanmadı" in report
        assert "boom" in report


class TestReportSurfacesRealAdapterData:
    def test_github_section_shows_real_repo_rows(self):
        repo = _repo()
        mission = _mission_with_task(
            "github",
            metadata={"report": {"category": "ai agent", "total_found": 12, "top": [
                {"repo": repo, "quality_score": 88.0, "risk_score": 5.0, "reason": "Olumlu: 4,200 yıldız"},
            ]}},
        )
        report = build_ceo_report(mission)
        assert "12 repository bulundu." in report
        assert "octocat/sample-agent" in report
        assert "4,200" in report
        assert "mit" in report

    def test_evaluation_section_shows_real_validation_pipeline_table(self):
        # Sprint 18: Evaluation bölümü artık AI Validation Pipeline'ın
        # tamamını (GitHub -> Evaluation -> Sandbox -> IntegrationPlanner
        # -> CEO kararı) tek bir tabloda gösterir.
        repo = _repo()
        evaluation = RepoEvaluation(
            name="sample-agent", url="https://github.com/octocat/sample-agent",
            overall_score=82.5, architecture_score=80, activity_score=90, community_score=70,
            license_score=100, security_score=85, compatibility_score=75, maintenance_score=80,
            relevance_score=95, recommendation="ÖNERİLİR — güçlü aday.",
            suitable_for_jarvis=True, target_module="src/agents", integration_difficulty="Düşük",
            risk_level="LOW",
        )
        integration_plan = IntegrationPlan(
            repository_name="octocat/sample-agent", repository_url="https://github.com/octocat/sample-agent",
            target_module="src/agents", target_package="src/agents", integration_strategy="genişlet",
            estimated_files=5, estimated_changes=6, estimated_risk="LOW", breaking_change_probability=5.0,
            merge_ready=True, summary="ok",
        )
        candidate = {
            "repo": repo, "evaluation": evaluation, "sandbox_verdict": "PASS",
            "integration_plan": integration_plan,
        }
        mission = _mission_with_task(
            "evaluation",
            metadata={"report": {"category": "ai agent", "candidates": [candidate], "summary": {"suitable_count": 1, "count": 1}}},
        )
        report = build_ceo_report(mission)
        assert "sample-agent" in report
        assert "82" in report
        assert "ÖNERİLİR" in report
        assert "PASS" in report
        assert "Düşük" in report  # Integration Difficulty
        assert "ÖNER" in report  # CEO kararı
        assert candidate["decision"] == "ÖNER"  # section render sırasında hesaplandı

    def test_sandbox_section_shows_pass_and_real_duration_not_fabricated_cpu_ram(self):
        result = SandboxResult(
            repository_name="octocat/sample-agent", repository_url="https://github.com/octocat/sample-agent",
            status=SandboxStatus.READY_FOR_REVIEW, total_size_mb=3.2, files_scanned=40,
            detected_language="Python", recommended_action="STATIC_ANALYSIS tamamlandı.",
        )
        mission = _mission_with_task(
            "sandbox",
            metadata={"report": {"repo": _repo(), "result": result, "duration_seconds": 4.21}},
        )
        report = build_ceo_report(mission)
        assert "PASS" in report
        assert "4.21" in report
        assert "ölçülmedi" in report  # CPU/RAM fabricated edilmedi

    def test_integration_section_shows_real_migration_steps(self):
        plan = IntegrationPlan(
            repository_name="octocat/sample-agent", repository_url="https://github.com/octocat/sample-agent",
            target_module="src/agents", target_package="src/agents", integration_strategy="genişlet",
            estimated_files=12, estimated_changes=15, estimated_risk="LOW", breaking_change_probability=5.0,
            migration_steps=["Sandbox bulgularını doğrula.", "src/agents altında yeni dosya oluştur."],
            merge_ready=True, summary="octocat/sample-agent -> src/agents, Risk: LOW.",
        )
        mission = _mission_with_task("integration", metadata={"report": {"repo": _repo(), "plan": plan}})
        report = build_ceo_report(mission)
        assert "1. Sandbox bulgularını doğrula." in report
        assert "Merge'e hazır: evet" in report
        assert "~12 dosya" in report

    def test_ceo_section_present_with_recommendation_and_next_step(self):
        mission = _mission_with_task("github")
        report = build_ceo_report(mission)
        assert "CEO" in report
        assert "Öneri:" in report
        assert "Sonuç:" in report
        assert "Sonraki adım:" in report


class TestCeoReportEndToEndWithRealHandlersNetworkMocked:
    def test_develop_jarvis_report_contains_all_four_sections_with_real_data(self, monkeypatch):
        repo = _repo()
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [repo])
        monkeypatch.setattr(
            SandboxManager, "run_pipeline",
            lambda self, url, evaluation, repo=None, **k: SandboxResult(
                repository_name=repo.full_name if repo else url, repository_url=url,
                status=SandboxStatus.READY_FOR_REVIEW, total_size_mb=1.0, files_scanned=5,
                recommended_action="ok",
            ),
        )
        monkeypatch.setattr(SandboxManager, "cleanup", lambda self, result: result)

        ceo = CEO()
        mission = ceo.create_mission("Jarvis'i geliştir.")
        ceo.dispatch_mission(mission)

        report = ceo.build_report(mission)

        assert "MISSION" in report
        assert "Jarvis'i geliştir." in report
        assert "Tür: CODE" in report
        assert "GitHub" in report and "octocat/sample-agent" in report
        assert "Evaluation" in report
        assert "Sandbox" in report and "PASS" in report
        assert "Integration" in report
        assert "CEO" in report
