from src.core.goal_engine import GoalEngine
from src.core.audit import Audit
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.mission_engine import MissionEngine
from src.mission.models import Mission
from src.mission.report_builder import build_ceo_report


class CEO:

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

    def create_mission(self, request, priority=1, deadline=None):
        """Bir kullanıcı isteğinden ``Mission`` üretir (``MissionEngine``
        üzerinden — mevcut ``GoalEngine``'i kullanır, ikinci bir hedef
        motoru OLUŞTURULMAZ)."""

        mission = self.mission_engine.create_mission(
            request, priority=priority, deadline=deadline,
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
        report = self.department_orchestrator.build_report(mission, plan, execution_report)

        self.audit.log(
            "CEO",
            f"Mission dağıtıldı: {mission.title!r} -> {mission.status.value}",
        )
        return plan, report

    def run_mission(self, request, priority=1, deadline=None):
        """Uçtan uca: create_mission + dispatch_mission tek çağrıda."""

        mission = self.create_mission(request, priority=priority, deadline=deadline)
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

    def report(self):

        return {
            "goals": self.goal_engine.all(),
            "last_log": self.audit.latest(),
        }