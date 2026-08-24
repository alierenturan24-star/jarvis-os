from src.core.goal_engine import GoalEngine
from src.core.audit import Audit
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.mission_engine import MissionEngine
from src.mission.models import Mission, MissionStatus
from src.mission.recovery import plan_needs_recovery, recover_mission
from src.mission.report_builder import build_ceo_report
from src.providers.provider_manager import ProviderManager
from src.research_loop.loop_engine import ResearchLoopEngine
from src.research_loop.models import ResearchLoopResult
from src.research_loop.report_builder import format_report as format_research_loop_report
from src.strategy.execution_planner import build_self_check
from datetime import datetime, timezone
import traceback


class CEO:

    def _record_internal_error(self, mission, component: str, error: Exception) -> None:
        context = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "component": component,
            "mission_id": str(getattr(mission, "id", "") or ""),
            "mission_title": str(getattr(mission, "title", "") or ""),
            "exception_type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        }
        errors = list(getattr(mission, "error_context", []) or [])
        errors.append(context)
        mission.error_context = errors
        self.audit.log("CEO_INTERNAL_ERROR", context)

    def __init__(self):

        self.goal_engine = GoalEngine()
        self.audit = Audit()

        # Sprint 13: mevcut CEO katmanı DepartmentOrchestrator/MissionEngine
        # ile GENİŞLETİLDİ — yeni bir CEO ya da Goal Engine YAZILMADI.
        # MissionEngine, aynı self.goal_engine örneğini kullanır (ikinci
        # bir hedef kaynağı OLUŞTURULMAZ).
        self.department_orchestrator = DepartmentOrchestrator()
        self.mission_engine = MissionEngine(
            goal_engine=self.goal_engine,
            orchestrator=self.department_orchestrator,
        )

        # Sprint 42 (AUTONOMOUS GOAL EXECUTION): ``dispatch_mission``'ın
        # kurtarma denemesi için kullandığı, ZATEN VAR OLAN
        # ``ProviderManager`` -- ikinci bir provider erişim katmanı İCAT
        # EDİLMEDİ.
        self.provider_manager = ProviderManager()

        # Sprint 37: AUTONOMOUS RESEARCH LOOP -- yeni bir ikinci CEO/Mission
        # sistemi DEĞİL, ZATEN VAR OLAN ``create_mission``/``dispatch_mission``'ı
        # (bu ikisi DEĞİŞTİRİLMEDİ) sınırlı sayıda tur çalıştıran bir
        # sarmalayıcı (bkz. ``src.research_loop.loop_engine``).
        self.research_loop_engine = ResearchLoopEngine(self)

    def start_day(self):

        self.audit.log(
            "CEO",
            "Yeni çalışma günü başlatıldı."
        )

    def choose_department(self, message):

        text = message.lower()

        if any(x in text for x in [
            "araştır",
            "incele",
            "haber",
        ]):
            return "research"

        if any(x in text for x in [
            "google",
            "youtube",
            "github",
            "aç",
        ]):
            return "browser"

        if any(x in text for x in [
            "kod",
            "python",
            "hata",
            "debug",
        ]):
            return "coding"

        return "chat"

    # --- Sprint 13: Mission katmanı (DepartmentOrchestrator üzerinden) -------------

    def select_departments(self, message):
        """``choose_department()``'in ÇOK-departmanlı hali — tek bir
        dize yerine bir departman listesi döndürür. Mevcut
        ``choose_department()`` GERİYE DÖNÜK UYUMLULUK için aynen
        kalır; bu, onu DEĞİŞTİRMEZ."""

        return self.department_orchestrator.select_departments(message)

    def create_mission(self, request, priority=1, deadline=None, execution_hints=None):
        """Bir kullanıcı isteğinden ``Mission`` üretir (``MissionEngine``
        üzerinden — mevcut ``GoalEngine``'i kullanır, ikinci bir hedef
        motoru OLUŞTURULMAZ)."""

        mission = self.mission_engine.create_mission(
            request, priority=priority, deadline=deadline, execution_hints=execution_hints,
        )
        self.audit.log(
            "CEO",
            f"Mission oluşturuldu: {mission.title!r} "
            f"(tür: {mission.mission_type.value}, departmanlar: {mission.departments})",
        )
        return mission

    def dispatch_mission(self, mission):
        """``Mission`` → ``TaskPlan`` → gerçek Execution Engine
        (``PlanExecutor``) zincirini çalıştırır. CEO işi KENDİSİ
        yapmaz — ``DepartmentOrchestrator``'a devreder."""

        plan = self.mission_engine.build_task_plan(mission)
        execution_report = self.department_orchestrator.dispatch(mission, plan)

        # Sprint 42/43 (AUTONOMOUS GOAL EXECUTION + FALSE SUCCESS RECOVERY):
        # dispatch SONRASI, GERÇEKTEN başarısız kalan görev varsa --
        # (klasik ``TaskStatus.FAILED`` VEYA Sprint 43 FALSE SUCCESS,
        # ``COMPLETED`` görünüp ``build_self_check``'in ZATEN tespit ettiği
        # "gerçek içerik üretilemedi" durumu) -- "provider'ı değil hedefi
        # koru" ilkesiyle kurtarma denenir (bkz.
        # ``src.mission.recovery.recover_mission``/``plan_needs_recovery``).
        # Yeni bir Mission/Plan sistemi İCAT EDİLMEZ, AYNI ``plan`` üzerinde
        # çalışılır (checkpoint/resume: yalnızca başarısız/sahte-başarılı
        # görev ve onun bağımlıları yeniden ele alınır, GERÇEKTEN
        # TAMAMLANMIŞ görevler ASLA yeniden çalıştırılmaz). Kurtarma
        # kendisi ARIZALANSA bile (ör. beklenmeyen bir hata) Mission
        # dispatch'ini KESMEZ -- eski davranışa güvenli şekilde düşülür.
        try:
            if plan_needs_recovery(plan, mission):
                print("[AŞAMA: RECOVERY]", flush=True)
                mission.recovery = recover_mission(
                    mission, plan, provider_manager=self.provider_manager,
                )
                from src.mission.task_criticality import critical_failures
                execution_report.success = not critical_failures(plan)
                mission.status = (
                    MissionStatus.FAILED if plan_needs_recovery(plan, mission) else MissionStatus.COMPLETED
                )
                from src.mission.completion import evidence_progress
                mission.progress = evidence_progress(mission, DepartmentOrchestrator._compute_progress(plan))
        except Exception as error:
            self._record_internal_error(mission, "mission_recovery", error)
            mission.recovery = None

        # Sprint 36 SELF CHECK: "Her görev sonunda" otomatik raporlanır
        # (Sprint 35'in aksine -- burada bir AYAR/PROVIDER DEĞİŞTİRİLMEZ,
        # yalnızca ZATEN hesaplanmış sonuçlardan bir özet üretilir, bkz.
        # ``src.strategy.execution_planner.build_self_check``). Başarısız
        # olursa (ör. ai_strategy yok) Mission dispatch'ini KESMEZ.
        try:
            review = self.review_ai_strategy(mission)
            mission.self_check = build_self_check(mission, review)
        except Exception as error:
            self._record_internal_error(mission, "mission_self_check", error)
            mission.self_check = None

        # A clean TaskPlan is not enough when the user requested a concrete
        # artifact/evidence output. Keep ordinary execution failures FAILED;
        # otherwise expose goal-level INCOMPLETE/BLOCKED explicitly.
        from src.mission.completion import evaluate_goal_completion
        goal_completion = evaluate_goal_completion(mission)
        if goal_completion.missing:
            mission.status = (
                MissionStatus.BLOCKED
                if mission.recovery is not None and mission.recovery.blocked
                else MissionStatus.INCOMPLETE
            )
        from src.mission.completion import evidence_progress
        mission.progress = evidence_progress(mission, mission.progress)

        execution_report.success = mission.status == MissionStatus.COMPLETED
        report = self.department_orchestrator.build_report(mission, plan, execution_report)

        self.audit.log(
            "CEO",
            f"Mission dağıtıldı: {mission.title!r} -> {mission.status.value}",
        )
        return plan, report

    def run_mission(self, request, priority=1, deadline=None, execution_hints=None):
        """Uçtan uca: create_mission + dispatch_mission tek çağrıda."""

        mission = self.create_mission(
            request, priority=priority, deadline=deadline, execution_hints=execution_hints,
        )
        plan, report = self.dispatch_mission(mission)
        return mission, plan, report

    # --- Sprint 16: CEO Report Engine -----------------------------------------------

    def build_report(self, mission: Mission) -> str:
        """``mission.tasks``'ın (dispatch_mission SONRASI, her görevin
        ``metadata['report']``'ında duran GERÇEK GitHubIntelligence/
        EvaluationEngine/SandboxManager/IntegrationPlanner çıktıları --
        bkz. ``src.mission.department_adapters``) kullanıcının
        okuyabileceği profesyonel bir CEO raporuna dönüştürür. Yeni bir
        analiz/puanlama/rapor motoru İCAT ETMEZ -- yalnızca zaten
        hesaplanmış sonuçları birleştirir (bkz. ``src.mission.report_builder``)."""

        return build_ceo_report(mission)

    # --- Sprint 35: AI Strategy geri bildirimi ---------------------------------------

    def review_ai_strategy(self, mission: Mission):
        """Mission sonunda ÇAĞRILABİLİR (otomatik ÇAĞRILMAZ -- Sprint 35
        KURAL: "bu sprintte kendi kendine ayar değiştirmesin"). Sprint
        34'te hazırlanan ``AIStrategyEngine.review()``'i, mission'ın
        GERÇEK ``ai_discovery`` sonucuyla (varsa) besler; yeni bir
        değerlendirme mantığı İCAT ETMEZ, yalnızca ZATEN hesaplanmış
        plan + (varsa) AI Discovery bulgularını okur ve raporlar."""

        if mission.ai_strategy is None:
            return None

        ai_discovery_task = next((task for task in mission.tasks if task.agent == "ai_discovery"), None)
        ai_discovery_report = ai_discovery_task.metadata.get("report") if ai_discovery_task else None

        return self.mission_engine.strategy_engine.review(
            mission.ai_strategy, ai_discovery_report=ai_discovery_report,
        )

    def report(self):

        return {
            "goals": self.goal_engine.all(),
            "last_log": self.audit.latest(),
        }

    # --- Sprint 37: Autonomous Research & Self-Improvement Loop --------------------

    def run_research_loop(self, goal: str, max_rounds: int | None = None) -> ResearchLoopResult:
        """Sınırlı sayıda ("Makul maksimum araştırma turu", Sprint 37 bölüm 2)
        turdan oluşan bir araştırma döngüsü çalıştırır. Her tur ZATEN VAR
        OLAN ``run_mission``'ın (create_mission + dispatch_mission,
        DEĞİŞTİRİLMEDİ) kendisidir -- yeni bir yürütme mekanizması İCAT
        ETMEZ, yalnızca ZATEN hesaplanan ``mission.self_check``'e göre
        durup durmayacağına karar verir (bkz. ``src.research_loop``).
        """

        self.audit.log("CEO", f"Research loop başlatıldı: {goal!r}")
        result = self.research_loop_engine.run(goal, max_rounds=max_rounds)
        self.audit.log(
            "CEO",
            f"Research loop bitti: {len(result.rounds)} tur, "
            f"{len(result.candidates)} aday, durma nedeni: {result.stopped_reason}",
        )
        return result

    def build_research_loop_report(self, result: ResearchLoopResult) -> str:
        """``run_research_loop``'ın sonucunu okunabilir bir metne çevirir.
        Her turun bölümü ZATEN VAR OLAN ``build_report``/``build_ceo_report``
        ile üretilir -- yeni bir rapor motoru İCAT ETMEZ (bkz.
        ``src.research_loop.report_builder.format_report``)."""

        return format_research_loop_report(result)
