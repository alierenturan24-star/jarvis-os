from __future__ import annotations

from src.core.ceo import CEO
from src.evolution.collector import EvolutionCollector
from src.github.github_intelligence import GitHubIntelligence
from src.github.models import RepoData
from src.jobs.task import Task
from src.jobs.task_status import TaskStatus
from src.mission.department import classify_mission_type, detect_mission_type
from src.mission.department_adapters import AIDiscoveryDepartmentAgent, DepartmentAdapterRegistry
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.models import MissionType
from src.research.manager import ResearchManager
from src.sandbox.models import SandboxResult, SandboxStatus
from src.sandbox.sandbox_manager import SandboxManager

REQUEST = "Yeni ücretsiz AI araçlarını araştır."


def _repo(name: str = "octocat/sample-agent", stars: int = 500) -> RepoData:
    return RepoData(
        name=name.split("/")[-1], full_name=name, url=f"https://github.com/{name}",
        description="test", stars=stars, forks=1, license="mit",
        last_update="2026-01-01T00:00:00Z", language="Python", category="ai agent",
        open_issues=0, archived=False, contributors_count=5,
    )


class TestMissionTypeDetection:
    def test_free_ai_tools_request_classified_as_ai_discovery(self):
        assert classify_mission_type(REQUEST) == MissionType.AI_DISCOVERY
        assert detect_mission_type(REQUEST) == MissionType.AI_DISCOVERY

    def test_ai_discovery_bundle_includes_ai_discovery_github_evaluation(self):
        orchestrator = DepartmentOrchestrator()
        departments = orchestrator.select_departments(REQUEST)
        assert {"ai_discovery", "github", "evaluation"}.issubset(set(departments))

    def test_plain_research_request_not_misclassified(self):
        # Sprint 17 yeni anahtar kelimeleri (ör. "yeni model") genel
        # araştırma isteklerini yanlışlıkla AI_DISCOVERY'e düşürmemeli.
        assert classify_mission_type("Nvidia hakkında haber araştır.") == MissionType.RESEARCH


class TestAIDiscoveryDepartmentAgentCallsRealClasses:
    def test_collect_and_rank_invoked_on_real_evolution_classes(self, monkeypatch):
        calls = {}

        def fake_collect(self, focus="", max_results_per_query=3):
            calls["focus"] = focus
            return [
                {"query": "new free AI API credits developer tools", "title": "FreeLLM Toolkit",
                 "url": "https://github.com/example/freellm", "summary": "free open source local LLM agent"},
                {"query": "AI video automation open source tools", "title": "VidBot",
                 "url": "https://github.com/example/vidbot", "summary": "open source video automation agent"},
            ]

        monkeypatch.setattr(EvolutionCollector, "collect", fake_collect)

        agent = AIDiscoveryDepartmentAgent()
        assert isinstance(agent.collector, EvolutionCollector)

        task = Task(title="t", agent="ai_discovery", target=REQUEST)
        output = agent.execute(task)

        assert calls["focus"] == REQUEST
        assert "FreeLLM Toolkit" in output
        report = task.metadata["report"]
        assert report["total_found"] == 2
        assert len(report["top"]) == 2
        assert all("score" in item for item in report["top"])

    def test_no_results_reported_not_crashed(self, monkeypatch):
        monkeypatch.setattr(EvolutionCollector, "collect", lambda self, focus="", max_results_per_query=3: [])

        agent = AIDiscoveryDepartmentAgent()
        output = agent.execute(Task(title="t", agent="ai_discovery", target=REQUEST))

        assert "bulunamadı" in output


class TestRegistryConnectsAIDiscovery:
    def test_ai_discovery_resolves_to_ai_discovery_department_agent(self):
        registry = DepartmentAdapterRegistry()
        handler = registry.resolve("ai_discovery")
        assert handler is not None
        assert type(handler.__self__).__name__ == "AIDiscoveryDepartmentAgent"


class TestCeoReportIncludesAIDiscoverySection:
    def test_report_shows_ai_discovery_section_and_does_not_fabricate_benchmarks(self, monkeypatch):
        repo = _repo()

        def fake_collect(self, focus="", max_results_per_query=3):
            return [
                {"query": "new free AI API credits developer tools", "title": "FreeLLM Toolkit",
                 "url": "https://github.com/example/freellm", "summary": "free open source local LLM agent"},
            ]

        monkeypatch.setattr(EvolutionCollector, "collect", fake_collect)
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [repo])
        monkeypatch.setattr(
            SandboxManager, "run_pipeline",
            lambda self, url, evaluation, repo=None, **k: SandboxResult(
                repository_name=repo.full_name if repo else url, repository_url=url,
                status=SandboxStatus.READY_FOR_REVIEW, recommended_action="ok",
            ),
        )
        monkeypatch.setattr(SandboxManager, "cleanup", lambda self, result: result)
        monkeypatch.setattr(
            ResearchManager, "research", lambda self, topic, force_refresh=False: "Araştırma (test)."
        )

        ceo = CEO()
        mission = ceo.create_mission(REQUEST)
        assert mission.mission_type == MissionType.AI_DISCOVERY

        ceo.dispatch_mission(mission)
        report = ceo.build_report(mission)

        assert "AI Discovery" in report
        assert "FreeLLM Toolkit" in report
        assert "GitHub" in report
        assert "Evaluation" in report

        # "Not:" açıklama cümlesi karşılaştırmalı iddiaların RAPORLANMADIĞINI
        # belirtir; ama hiçbir adayın kendi satırında böyle bir iddia
        # GERÇEKTEN yer almamalı (yalnızca açıklama cümlesinde geçebilir).
        assert "ÖLÇÜLMEDİĞİ için raporlanmaz" in report
        assert "FreeLLM Toolkit" not in report.split("Not:")[-1]

        ai_task = next(t for t in mission.tasks if t.agent == "ai_discovery")
        assert ai_task.status == TaskStatus.COMPLETED

    def test_mission_without_ai_discovery_department_has_no_ai_discovery_section(self, monkeypatch):
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

        ceo = CEO()
        mission = ceo.create_mission("Jarvis'i geliştir.")
        ceo.dispatch_mission(mission)
        report = ceo.build_report(mission)

        assert "AI Discovery" not in report
