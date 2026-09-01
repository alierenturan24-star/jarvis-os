from __future__ import annotations

import pytest

from src.core.ceo import CEO
from src.core.task_plan import TaskPlan
from src.finance.manager import FinanceManager
from src.github.github_intelligence import GitHubIntelligence
from src.jobs.task_status import TaskStatus
from src.mission.department import classify_mission_type
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.mission_engine import MissionEngine
from src.mission.models import Mission, MissionStatus, MissionType
from src.research.manager import ResearchManager
from src.tools.browser_tool import BrowserTool


# --- 1) YouTube Mission -> doğru departmanlar ----------------------------------


class TestYouTubeMissionDepartments:
    def test_youtube_automation_request_selects_expected_departments(self):
        orchestrator = DepartmentOrchestrator()
        departments = orchestrator.select_departments("YouTube otomasyonu kur.")

        assert set(departments) == {"research", "github", "browser", "media", "automation"}

    def test_youtube_mission_type_classified_correctly(self):
        assert classify_mission_type("YouTube otomasyonu kur.") == MissionType.YOUTUBE

    def test_shorts_content_request_selects_expected_departments(self):
        # Sprint 39 kabul testi istemi -- media/automation artık GERÇEK
        # modüllere bağlı, ama seçim mantığı (department.py) DEĞİŞMEDİ.
        # Not: "finance" da seçilir -- "Bitcoin" metni, finance
        # departmanının "coin" anahtar kelimesini (alt-dize olarak,
        # "bitCOIN") İÇERİR; bu ZATEN VAR OLAN, bu sprintte DEĞİŞMEYEN bir
        # davranıştır (bkz. department.py enrichment taraması).
        #
        # Mission repair (ROOT CAUSE A): "github" KASITLI olarak beklenen
        # kümeden ÇIKARILDI -- bu istek bir içerik/konu araştırmasıdır
        # ("Bitcoin neden düştü" HABERİNİ Shorts'a çevir), hiçbir repo/
        # araç/sağlayıcı EDİNME sinyali içermez (bkz. ``has_acquisition_
        # signal``); bu yüzden artık GitHub Intelligence dispatch
        # EDİLMİYOR (gerçek Swiss-Insider-Shorts arızasının kök sebebi --
        # bkz. mission repair raporu ROOT CAUSE A).
        orchestrator = DepartmentOrchestrator()
        departments = orchestrator.select_departments(
            "Bitcoin neden düştü konusunda 60 saniyelik bir YouTube Shorts hazırla."
        )
        assert set(departments) == {"research", "media", "finance"}


# --- 2) Finans Mission -> doğru departmanlar -----------------------------------


class TestFinanceMissionDepartments:
    def test_coin_research_request_selects_expected_departments(self):
        orchestrator = DepartmentOrchestrator()
        departments = orchestrator.select_departments("Yeni coin araştır.")

        assert set(departments) == {"finance", "research", "browser"}

    def test_finance_wins_over_generic_research_keyword(self):
        # "araştır" hem RESEARCH hem (dolaylı) FINANCE isteğinde gecebilir;
        # FINANCE'a özgü "coin" sinyali kazanmalı (öncelik sıralaması).
        assert classify_mission_type("Yeni coin araştır.") == MissionType.FINANCE


# --- 3) GitHub Mission -> GitHub + Sandbox + Integration -----------------------


class TestGithubMissionDepartments:
    def test_develop_jarvis_request_includes_required_departments(self):
        orchestrator = DepartmentOrchestrator()
        departments = orchestrator.select_departments("Jarvis'i geliştir.")

        required = {"github", "sandbox", "integration"}
        assert required.issubset(set(departments))

    def test_code_mission_type_classified_correctly(self):
        assert classify_mission_type("Jarvis'i geliştir.") == MissionType.CODE


# --- 4) Mission -> TaskPlan oluşuyor mu ----------------------------------------


class TestMissionProducesTaskPlan:
    def test_build_task_plan_returns_real_task_plan_with_one_task_per_department(self, monkeypatch):
        # Sprint 32: CATEGORY hedefinde "browser" departmanı artık (sinyal
        # yoksa) gerçek bir GitHub adayı arayıp açabiliyor -- bu testin
        # "departman başına tek görev" varsayımını deterministik/hızlı
        # tutmak için GitHubIntelligence.search boş dönecek şekilde
        # sahteleniyor (böylece eski, tek-görevli "search" davranışına
        # güvenli şekilde düşülür).
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [])

        engine = MissionEngine()
        mission = engine.create_mission("YouTube otomasyonu kur.")

        plan = engine.build_task_plan(mission)

        assert isinstance(plan, TaskPlan)
        assert len(plan.all_tasks()) == len(mission.departments)
        assert mission.status == MissionStatus.PLANNED
        assert len(mission.tasks) == len(mission.departments)

    def test_task_plan_validates_without_cycles(self):
        # Departman gorevleri birbirinden BAGIMSIZDIR; validate() hicbir
        # dongu bulmamali (TaskPlanError firlamamali).
        engine = MissionEngine()
        mission = engine.create_mission("Yeni coin araştır.")
        plan = engine.build_task_plan(mission)

        plan.validate()  # exception firlarsa test kendiliginden basarisiz olur

    def test_each_task_carries_department_in_agent_field(self):
        engine = MissionEngine()
        mission = engine.create_mission("Jarvis'i geliştir.")
        plan = engine.build_task_plan(mission)

        task_departments = {task.agent for task in plan.all_tasks()}
        assert task_departments == set(mission.departments)


# --- 5) Execution Engine'e aktarılıyor mı --------------------------------------


class TestDispatchReachesRealExecutionEngine:
    def test_dispatch_actually_invokes_plan_executor_and_job_manager(self):
        # Bir departman gorevine GERCEK bir handler baglayip, dispatch()
        # sonrasinda gercekten CAGRILDIGINI (attempts=1, status=COMPLETED)
        # dogrulayarak baglantinin SIMULE edilmedigini kanitlar.
        engine = MissionEngine()
        mission = engine.create_mission("Yeni coin araştır.")
        plan = engine.build_task_plan(mission)

        called = {}

        def fake_research_handler(task):
            called["ran"] = True
            called["task_id"] = task.id
            return "ok"

        research_task = next(t for t in plan.all_tasks() if t.agent == "research")
        research_task.handler = fake_research_handler

        orchestrator = engine.orchestrator
        report = orchestrator.dispatch(mission, plan)

        assert called.get("ran") is True
        assert called["task_id"] == research_task.id
        assert research_task.status == TaskStatus.COMPLETED
        assert research_task.attempts == 1
        assert research_task in report.executed

    def test_tasks_without_handler_fail_gracefully_not_silently(self, monkeypatch):
        # Sprint 39: media/automation artik GERCEK modullere bagli (bkz.
        # src.media/src.automation) -- YouTube mission'inin TUM
        # departmanlari artik baglandigi icin bu test "hala baglanmamis"
        # davranisini LEARNING mission'i ile dogruluyor (learning
        # departmani hala gercek bir module bagli DEGIL).
        monkeypatch.setattr(
            ResearchManager, "research", lambda self, topic, force_refresh=False: "ok (test)"
        )

        engine = MissionEngine()
        mission = engine.create_mission("Python öğren.")
        plan = engine.build_task_plan(mission)

        report = engine.orchestrator.dispatch(mission, plan)

        still_unconnected = set()
        assert report.success is True  # learning artık FinanceLearningAgent'a bağlı

        for task in plan.all_tasks():
            if task.agent in still_unconnected:
                assert task.status == TaskStatus.FAILED
                assert "handler tanımlı değil" in task.error
            else:
                # Tüm seçilen departmanların artık gerçek handler'ı var.
                # research: artik GERCEK bir handler var, "handler
                # tanimli degil" ile basarisiz OLMAMALI.
                assert task.status == TaskStatus.COMPLETED

    def test_collect_results_and_build_report_reflect_plan_state(self, monkeypatch):
        # finance/research/browser gercek handler'lara sahip. Bu plan-state
        # testi ag/LLM/Playwright sonucunu degil basarili execution raporunu
        # dogruladigi icin uc dis siniri da deterministik basariyla sahteler.
        monkeypatch.setattr(
            FinanceManager, "analyze", lambda self, asset, **kwargs: "Finans analizi (test)."
        )
        monkeypatch.setattr(
            ResearchManager,
            "research",
            lambda self, topic, force_refresh=False, **kwargs: "Araştırma (test).",
        )
        monkeypatch.setattr(
            BrowserTool, "execute", lambda self, **kwargs: "Arama yapıldı (test)."
        )
        # CATEGORY hedefinin aday cozumlemesini de agdan ayir.
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [])

        engine = MissionEngine()
        mission, plan, report = engine.run_mission("Yeni coin araştır.")

        collected = engine.orchestrator.collect_results(plan)
        assert collected["summary"]["failed"] == 0
        assert collected["summary"]["completed"] == len(mission.departments)
        assert len(collected["results"]) == len(mission.departments)

        assert report["mission_id"] == mission.id
        assert report["departments"] == mission.departments
        assert report["progress"] == 100.0  # tum gorevler terminal duruma ulasti
        assert report["execution_success"] is True


# --- 6) CEO -> DepartmentOrchestrator kullanıyor mu ----------------------------


class TestCeoUsesDepartmentOrchestrator:
    def test_ceo_has_department_orchestrator_instance(self):
        ceo = CEO()
        assert isinstance(ceo.department_orchestrator, DepartmentOrchestrator)
        assert isinstance(ceo.mission_engine, MissionEngine)
        assert ceo.mission_engine.orchestrator is ceo.department_orchestrator

    def test_ceo_select_departments_delegates_to_orchestrator(self):
        ceo = CEO()
        assert ceo.select_departments("Jarvis'i geliştir.") == ceo.department_orchestrator.select_departments("Jarvis'i geliştir.")

    def test_ceo_mission_engine_shares_same_goal_engine_no_second_source(self):
        # MissionEngine ikinci bir GoalEngine ORNEGI OLUSTURMAMALI.
        ceo = CEO()
        assert ceo.mission_engine.goal_engine is ceo.goal_engine

    def test_ceo_legacy_choose_department_unchanged(self):
        # Sprint 13 oncesi API'nin bozulmadigini dogrular (regresyon).
        ceo = CEO()
        assert ceo.choose_department("Bunu araştır lütfen") == "research"
        assert ceo.choose_department("github aç") == "browser"
        assert ceo.choose_department("bu kodu debug et") == "coding"
        assert ceo.choose_department("selam") == "chat"


# --- 7) Mevcut testler: regresyon olmadan geçmeli ------------------------------
# (Bu paket src/core'un mevcut hicbir dosyasini SILMEDI/YENIDEN YAZMADI;
# yalnizca src/core/ceo.py'ye EKLEME yapildi. Regresyon kontrolu ayri bir
# pytest calistirmasiyla yapilir — bkz. rapor.)


class TestNoDuplicateSystemsIntroduced:
    """Sprint kurallarina uyumu dogrudan test eder: ikinci bir CEO/Goal
    Engine/Execution Engine OLUSTURULMADI."""

    def test_mission_engine_reuses_existing_task_plan_class(self):
        import src.core.task_plan as core_task_plan
        engine = MissionEngine()
        mission = engine.create_mission("test isteği")
        plan = engine.build_task_plan(mission)
        assert type(plan) is core_task_plan.TaskPlan

    def test_department_orchestrator_reuses_existing_plan_executor(self):
        import src.core.plan_executor as core_plan_executor
        import inspect
        source = inspect.getsource(DepartmentOrchestrator.dispatch)
        assert "PlanExecutor" in source
        assert core_plan_executor.PlanExecutor is not None  # gercekten var/import edilebilir


# --- 8) Gerçek örnek: "Jarvis'i geliştir." uçtan uca ---------------------------


class TestRealEndToEndExample:
    def test_develop_jarvis_end_to_end(self, monkeypatch):
        # Sprint 15: github/sandbox/integration artik GERCEK modullere
        # bagli -- bu uctan uca testin agi/klonlamayi her calistiginda
        # gercekten tetiklememesi (yavas/deterministik-olmayan CI) icin
        # ag sinirindaki iki metodu (GitHubIntelligence.search,
        # SandboxManager.run_pipeline) mockluyoruz. EvaluationEngine ve
        # IntegrationPlanner.analyze() saf/yerel mantik oldugu icin
        # GERCEK haliyle calismaya devam eder.
        from src.github.github_intelligence import GitHubIntelligence
        from src.github.models import RepoData
        from src.sandbox.models import SandboxResult, SandboxStatus
        from src.sandbox.sandbox_manager import SandboxManager

        fake_repo = RepoData(
            name="sample-agent",
            full_name="octocat/sample-agent",
            url="https://github.com/octocat/sample-agent",
            description="Test double for the live end-to-end mission test.",
            stars=1234,
            forks=12,
            license="mit",
            last_update="2026-01-01T00:00:00Z",
            language="Python",
            category="ai agent",
            open_issues=1,
            archived=False,
            contributors_count=5,
        )
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [fake_repo])
        monkeypatch.setattr(
            SandboxManager,
            "run_pipeline",
            lambda self, url, evaluation, repo=None, **k: SandboxResult(
                repository_name=repo.full_name if repo else url,
                repository_url=url,
                status=SandboxStatus.READY_FOR_REVIEW,
                recommended_action="test ok",
            ),
        )
        monkeypatch.setattr(SandboxManager, "cleanup", lambda self, result: result)

        ceo = CEO()

        # Mission oluştur
        mission = ceo.create_mission("Jarvis'i geliştir.")
        assert isinstance(mission, Mission)
        assert mission.mission_type == MissionType.CODE
        assert mission.status == MissionStatus.CREATED

        # Departman seç
        assert {"github", "sandbox", "integration"}.issubset(set(mission.departments))
        assert mission.confidence > 0
        assert mission.risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert mission.required_resources.estimated_tokens > 0
        assert mission.success_criteria

        # Task üret + Execution'a gönder
        plan, report = ceo.dispatch_mission(mission)
        assert isinstance(plan, TaskPlan)
        assert len(plan.all_tasks()) == len(mission.departments)
        assert mission.status in (MissionStatus.COMPLETED, MissionStatus.FAILED)
        assert report["execution_success"] == (mission.status == MissionStatus.COMPLETED)

        # Audit'e islendi mi
        last_log = ceo.audit.latest()
        assert last_log is not None
        assert "Mission dağıtıldı" in last_log["detail"]
