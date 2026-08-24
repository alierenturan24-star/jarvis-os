from __future__ import annotations

from src.core.ceo import CEO
from src.finance.manager import FinanceManager
from src.github.github_intelligence import GitHubIntelligence
from src.mission.department import classify_mission_type
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.mission_engine import MissionEngine
from src.mission.models import MissionType
from src.providers.cost_optimizer import CostOptimizer
from src.providers.provider_manager import ProviderManager
from src.research.manager import ResearchManager
from src.sandbox.models import SandboxResult, SandboxStatus
from src.sandbox.sandbox_manager import SandboxManager
from src.strategy.strategy_engine import AIStrategyEngine

# Sprint 35 örnek görevleri (bkz. KABUL TESTLERİ).
SHORTS_TASK_1 = "100 Shorts fikri üret."
SHORTS_TASK_2 = "Shorts içerik fikirleri üret."
SHORTS_TASK_3 = "Video fikirleri üret."
FINANCE_TASK = "Bitcoin neden düştü?"
CODE_TASK = "Bu Python hatasını çöz."
YOUTUBE_REPO_TASK = "YouTube için en iyi otomasyon reposunu bul."


class _FakeProvider:
    def __init__(self, available: bool) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, model: str | None = None) -> str:
        return f"[fake-response from {self.__class__.__name__}]"


ALL_PROVIDERS = ("ollama", "aiml", "openai", "anthropic", "gemini", "deepseek", "groq", "openrouter")


class _FakeProviderManager:
    def __init__(self, available: set[str]) -> None:
        self._available = available

    def get(self, name: str):
        normalized = ProviderManager.normalize(name)
        if normalized not in ALL_PROVIDERS:
            return None
        return _FakeProvider(normalized in self._available)

    def available_names(self) -> list[str]:
        return [name for name in ALL_PROVIDERS if name in self._available]


def _mission_engine(available: set[str]) -> MissionEngine:
    orchestrator = DepartmentOrchestrator()
    cost_optimizer = CostOptimizer(provider_manager=_FakeProviderManager(available))
    strategy_engine = AIStrategyEngine(orchestrator=orchestrator, cost_optimizer=cost_optimizer)
    return MissionEngine(orchestrator=orchestrator, strategy_engine=strategy_engine)


# --- 1) Mission sınıflandırma düzeltmesi ----------------------------------------


class TestYoutubeContentClassificationFix:
    def test_shorts_idea_task_is_youtube(self):
        assert classify_mission_type(SHORTS_TASK_1) == MissionType.YOUTUBE

    def test_shorts_content_ideas_task_is_youtube(self):
        assert classify_mission_type(SHORTS_TASK_2) == MissionType.YOUTUBE

    def test_video_ideas_task_is_youtube(self):
        assert classify_mission_type(SHORTS_TASK_3) == MissionType.YOUTUBE

    def test_other_classifications_unaffected(self):
        # Regresyon: mevcut sınıflandırmalar bozulmadı.
        assert classify_mission_type("Jarvis'i geliştir.") == MissionType.CODE
        assert classify_mission_type("Yeni coin araştır.") == MissionType.FINANCE
        assert classify_mission_type("Bu konuyu araştır.") == MissionType.RESEARCH
        assert classify_mission_type("YouTube otomasyonu kur.") == MissionType.YOUTUBE

    def test_media_classification_not_hijacked_by_new_youtube_keywords(self):
        # "video üret"/"içerik üret" (MEDIA) hâlâ MEDIA olarak sınıflanır --
        # yeni "video fikri"/"video fikirleri"/"shorts" sinyalleriyle
        # ÇAKIŞMAZ.
        assert classify_mission_type("Bir video üret.") == MissionType.MEDIA
        # Not: büyük "İ" kasıtlı olarak KULLANILMADI -- Python'da "İ".lower()
        # düz "i" değil, birleşen noktalı "i" üretir (bkz. department.py'deki
        # "i̇nternette" notu); bu, bu testin konusu OLMAYAN, önceden var
        # olan bir Türkçe casefold tuhaflığıdır.
        assert classify_mission_type("içerik üret.") == MissionType.MEDIA


# --- 2) AI Strategy gerçek akışa bağlı mı ----------------------------------------


class TestMissionCarriesAIStrategyPlan:
    def test_create_mission_populates_ai_strategy(self):
        engine = _mission_engine(available={"ollama"})
        mission = engine.create_mission(SHORTS_TASK_1)

        assert mission.ai_strategy is not None
        assert mission.ai_strategy.request == SHORTS_TASK_1
        assert {c.name for c in mission.ai_strategy.departments} == set(mission.departments)

    def test_shorts_task_mission_type_is_youtube_end_to_end(self):
        engine = _mission_engine(available={"ollama"})
        mission = engine.create_mission(SHORTS_TASK_1)
        assert mission.mission_type == MissionType.YOUTUBE

    def test_strategy_engine_shares_same_orchestrator_no_second_department_system(self):
        engine = _mission_engine(available={"ollama"})
        assert engine.strategy_engine.orchestrator is engine.orchestrator

    def test_planning_failure_does_not_break_mission_creation(self, monkeypatch):
        # KURAL: AI Strategy hiçbir görevi çalıştırmaz VE planlama
        # başarısız olsa bile Mission/Department sistemi bozulmamalı.
        orchestrator = DepartmentOrchestrator()
        strategy_engine = AIStrategyEngine(orchestrator=orchestrator)

        def boom(request):
            raise RuntimeError("Kullanılabilir hiçbir yapay zekâ sağlayıcısı bulunamadı.")

        monkeypatch.setattr(strategy_engine, "plan", boom)
        engine = MissionEngine(orchestrator=orchestrator, strategy_engine=strategy_engine)

        mission = engine.create_mission(SHORTS_TASK_1)

        assert mission.ai_strategy is None
        assert mission.departments  # Mission/Department seçimi ETKİLENMEDİ


class TestPreferredProviderThreadedIntoTaskMetadata:
    def test_research_task_receives_preferred_ai_provider(self, monkeypatch):
        # Sprint 41: SHORTS_TASK_1 ("100 Shorts fikri üret.") artık saf
        # üretim sinyali taşıdığı için research'ü İÇERMİYOR (bkz.
        # ``_narrow_pure_generation_youtube``) -- bu test hâlâ research
        # gerektiren YOUTUBE_REPO_TASK'a geçirildi.
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [])
        engine = _mission_engine(available={"ollama"})
        mission = engine.create_mission(YOUTUBE_REPO_TASK)
        plan = engine.build_task_plan(mission)

        research_task = next(t for t in plan.all_tasks() if t.agent == "research")
        assert research_task.metadata.get("preferred_ai_provider") == mission.ai_strategy.ai_choice.provider

    def test_no_metadata_key_when_ai_strategy_missing(self):
        # Mission'ı doğrudan (MissionEngine atlanarak) oluşturan eski/test
        # kodu için: ai_strategy yoksa preferred_ai_provider da YOK --
        # departmanlar kendi eski varsayılanına düşer.
        from src.mission.models import Mission

        orchestrator = DepartmentOrchestrator()
        mission = Mission(title=FINANCE_TASK, description=FINANCE_TASK, departments=["finance"])
        tasks = orchestrator.create_tasks(mission)

        finance_task = next(t for t in tasks if t.agent == "finance")
        assert "preferred_ai_provider" not in finance_task.metadata


class TestSprint40TaskLevelRouting:
    """Sprint 40: "tek mission = tek provider" KALDIRILDI -- aynı mission
    içindeki farklı departmanlar (research/finance/media) FARKLI provider
    seçebilmeli, hepsi AYNI ``mission.ai_strategy.ai_choice.provider``'a
    zorlanmamalı."""

    def test_research_and_finance_get_independently_computed_providers(self, monkeypatch):
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [])
        # research -> gemini (ücretsiz kotalı, karmaşık görev sınıfının
        # öncelikli adayı) kullanılabilirken finance -> yalnızca ollama
        # kullanılabilir (TASK_FINANCE'ın ücretsiz kotalı bir adayı YOK).
        engine = _mission_engine(available={"ollama", "gemini"})
        mission = engine.create_mission(
            "Bitcoin neden düştü konusunda 60 saniyelik bir YouTube Shorts hazırla."
        )
        plan = engine.build_task_plan(mission)

        research_task = next(t for t in plan.all_tasks() if t.agent == "research")
        finance_task = next(t for t in plan.all_tasks() if t.agent == "finance")

        assert research_task.metadata.get("preferred_ai_provider") == "gemini"
        assert finance_task.metadata.get("preferred_ai_provider") == "ollama"
        # İKİ departman AYNI mission içinde FARKLI provider aldı -- Sprint
        # 40'ın asıl iddiası budur.
        assert research_task.metadata.get("preferred_ai_provider") != finance_task.metadata.get(
            "preferred_ai_provider"
        )

    def test_llm_free_departments_fall_back_to_flat_mission_choice(self, monkeypatch):
        # github/browser gibi departman_ai_choices'ta hiç YOKTUR -- eski
        # (mission-seviyesi) davranışa güvenli bir şekilde düşerler.
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [])
        engine = _mission_engine(available={"ollama"})
        mission = engine.create_mission(
            "Bitcoin neden düştü konusunda 60 saniyelik bir YouTube Shorts hazırla."
        )
        plan = engine.build_task_plan(mission)

        github_task = next(t for t in plan.all_tasks() if t.agent == "github")
        assert github_task.metadata.get("preferred_ai_provider") == mission.ai_strategy.ai_choice.provider


# --- 3) Provider seçimi gerçekten ProviderManager/CostOptimizer üzerinden ---------


class TestProviderSelectionUsesExistingSystem:
    def test_route_and_generate_uses_preferred_provider_when_available(self):
        manager = ProviderManager()
        manager._providers = {  # type: ignore[attr-defined]
            "ollama": _FakeProvider(True),
            "groq": _FakeProvider(True),
        }
        result = manager.route_and_generate(
            prompt="test", task_type="long_research", preferred_provider="groq",
        )
        assert result.chosen_provider == "groq"
        assert "AI Strategy" in result.reason

    def test_route_and_generate_falls_back_when_preferred_unavailable(self):
        manager = ProviderManager()
        manager._providers = {  # type: ignore[attr-defined]
            "ollama": _FakeProvider(True),
            "aiml": _FakeProvider(False),
        }
        result = manager.route_and_generate(
            prompt="test", task_type="long_research", preferred_provider="aiml",
        )
        # aiml kullanılamıyor -> eski görev-türü tablosuna (ollama/aiml
        # karar mantığı) düşülür, ASLA istisna fırlatmaz.
        assert result.chosen_provider in ("ollama", "aiml")

    def test_route_and_generate_without_preferred_is_unchanged(self):
        # preferred_provider verilmezse davranış BİREBİR eskisi gibi.
        manager = ProviderManager()
        manager._providers = {  # type: ignore[attr-defined]
            "ollama": _FakeProvider(True),
        }
        result = manager.route_and_generate(prompt="test", task_type="short_chat")
        assert result.chosen_provider == "ollama"

    def test_finance_manager_resolve_provider_defaults_to_ollama(self):
        finance_manager = FinanceManager()
        finance_manager.router.manager._providers = {  # type: ignore[attr-defined]
            "ollama": _FakeProvider(True),
        }
        assert finance_manager._resolve_provider(None) == "ollama"

    def test_finance_manager_resolve_provider_uses_available_preferred(self):
        finance_manager = FinanceManager()
        finance_manager.router.manager._providers = {  # type: ignore[attr-defined]
            "ollama": _FakeProvider(True),
            "groq": _FakeProvider(True),
        }
        assert finance_manager._resolve_provider("groq") == "groq"

    def test_finance_manager_resolve_provider_falls_back_when_unavailable(self):
        finance_manager = FinanceManager()
        finance_manager.router.manager._providers = {  # type: ignore[attr-defined]
            "ollama": _FakeProvider(True),
            "anthropic": _FakeProvider(False),
        }
        assert finance_manager._resolve_provider("anthropic") == "ollama"


# --- 4) CEO raporu -----------------------------------------------------------------


class TestCeoReportShowsAIStrategySection:
    def test_report_contains_ai_strategy_section_with_required_fields(self, monkeypatch):
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [])
        # Sprint 15/19 test kalıbıyla AYNI: gerçek ağ/LLM çağrısı içeren
        # FinanceManager.analyze() sahtelenir -- testin deterministik/
        # hızlı kalması için (bkz. test_mission_engine.py'deki AYNI kalıp).
        monkeypatch.setattr(
            FinanceManager, "analyze",
            lambda self, asset, preferred_provider=None: f"ok (test, provider={preferred_provider})",
        )
        engine = _mission_engine(available={"ollama"})
        ceo = CEO()
        ceo.mission_engine = engine
        ceo.department_orchestrator = engine.orchestrator

        mission = ceo.create_mission(FINANCE_TASK)
        ceo.dispatch_mission(mission)
        report = ceo.build_report(mission)

        assert "AI STRATEGY" in report
        assert "Görev kategorisi:" in report
        assert "Seçilen provider:" in report
        assert "Maliyet katmanı:" in report
        assert "Kullanılan department'lar:" in report
        assert "Kullanılan tool'lar:" in report
        assert "Seçim gerekçesi:" in report

    def test_report_handles_missing_ai_strategy_gracefully(self):
        from src.mission.models import Mission

        mission = Mission(title="t", mission_type=MissionType.RESEARCH, departments=["research"])
        mission.tasks = []
        from src.mission.report_builder import build_ceo_report

        report = build_ceo_report(mission)
        assert "AI STRATEGY" in report
        assert "veri yok" in report


# --- 5) Geri bildirim (review) ------------------------------------------------------


class TestReviewAIStrategyCallable:
    def test_review_returns_none_without_ai_strategy(self):
        from src.mission.models import Mission

        ceo = CEO()
        mission = Mission(title="t", departments=[])
        assert ceo.review_ai_strategy(mission) is None

    def test_review_returns_self_improvement_review(self, monkeypatch):
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [])
        monkeypatch.setattr(
            ResearchManager, "research",
            lambda self, topic, force_refresh=False, preferred_provider=None: "ok (test)",
        )
        engine = _mission_engine(available={"ollama"})
        ceo = CEO()
        ceo.mission_engine = engine
        ceo.department_orchestrator = engine.orchestrator

        mission = ceo.create_mission(SHORTS_TASK_1)
        ceo.dispatch_mission(mission)

        review = ceo.review_ai_strategy(mission)
        assert review is not None
        assert isinstance(review.cheaper_ai_possible, bool)
        assert isinstance(review.new_free_model_available, bool)


# --- KABUL TESTİ #4: GitHub/Browser/Evaluation/Sandbox/Integration zinciri --------


class TestValidationPipelineChainUnaffected:
    def test_youtube_repo_selection_still_triggers_full_chain(self, monkeypatch):
        repo = _fake_repo()
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [repo])
        monkeypatch.setattr(
            SandboxManager, "run_pipeline",
            lambda self, url, evaluation, repo=None, **k: SandboxResult(
                repository_name=repo.full_name if repo else url, repository_url=url,
                status=SandboxStatus.READY_FOR_REVIEW, recommended_action="ok",
            ),
        )
        monkeypatch.setattr(SandboxManager, "cleanup", lambda self, result: result)

        engine = _mission_engine(available={"ollama"})
        mission = engine.create_mission(YOUTUBE_REPO_TASK)

        assert mission.mission_type == MissionType.YOUTUBE
        names = set(mission.departments)
        assert {"github", "evaluation", "sandbox", "integration"}.issubset(names)


def _fake_repo():
    from src.github.models import RepoData

    return RepoData(
        name="youtube-automation-agent", full_name="darkzOGx/youtube-automation-agent",
        url="https://github.com/darkzOGx/youtube-automation-agent", description="test",
        stars=1771, forks=431, license="mit", last_update="2026-01-01T00:00:00Z",
        language="JavaScript", category="youtube automation",
    )
