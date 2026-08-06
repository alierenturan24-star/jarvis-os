from src.ai.brain import Brain
from src.core.agent_router import AgentRouter
from src.core.ceo import CEO
from src.core.workflow_engine import WorkflowEngine
from src.decision.decision_engine import DecisionEngine
from src.memory.memory_manager import MemoryManager
from src.mission.department import detect_mission_type


class Jarvis:
    def __init__(self) -> None:
        self.brain = Brain()
        self.decision_engine = DecisionEngine()
        self.agent_router = AgentRouter()
        self.workflow = WorkflowEngine(self.agent_router)
        self.memory = MemoryManager()

        # Sprint 14: mevcut CEO/Mission katmanına (Sprint 13) CANLI bağlantı.
        # WorkflowEngine DEĞİŞTİRİLMEDİ; Mission yalnızca gerçekten gerekli
        # olduğunda (bkz. _requires_mission) devreye girer, aksi halde eski
        # akış (self.workflow.run) AYNEN çalışmaya devam eder.
        self.ceo = CEO()

    def chat(self, message: str) -> str:
        message = message.strip()

        if not message:
            return "Boş komut gönderildi."

        decision = self.decision_engine.analyze(message)

        if decision.blocked:
            return (
                "Bu komut güvenlik nedeniyle engellendi.\n"
                f"Sebep: {decision.reason}"
            )

        if decision.confirmation:
            return (
                "Bu işlem açık onay gerektiriyor ve henüz çalıştırılmadı.\n"
                f"Sebep: {decision.reason}"
            )

        if self._requires_mission(message):
            return self._run_mission(message)

        return self.workflow.run(message)

    @staticmethod
    def _requires_mission(message: str) -> bool:
        """Mesaj, mevcut Mission sınıflandırıcısının (``src.mission``)
        tanıdığı en az bir alan-özel sinyal içeriyorsa ``True``. Düz
        sohbet ("Merhaba" gibi) hiçbir sinyalle eşleşmez → ``False`` →
        eski ``WorkflowEngine`` akışı BOZULMADAN devam eder."""

        return detect_mission_type(message) is not None

    def _run_mission(self, message: str) -> str:
        """Mission → TaskPlan → PlanExecutor → Execution zincirini
        (Sprint 13, DEĞİŞTİRİLMEDİ) CANLI olarak çalıştırır; sonucu
        Sprint 16'nın CEO Report Engine'i (``CEO.build_report`` ->
        ``src.mission.report_builder``) ile okunabilir bir CEO raporuna
        çevirir -- departmanların GERÇEK bulguları (GitHub/Evaluation/
        Sandbox/Integration) artık kullanıcıya YANSITILIR, yalnızca
        durum sayaçları değil."""

        mission, _plan, _report = self.ceo.run_mission(message)
        return self.ceo.build_report(mission)

    def remember(self, key, value):
        self.memory.save(key, value)

    def recall(self, key):
        return self.memory.load(key)
