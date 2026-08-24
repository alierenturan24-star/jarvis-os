from src.ai.brain import Brain
from src.core.agent_router import AgentRouter
from src.core.ceo import CEO
from src.core.workflow_engine import WorkflowEngine
from src.decision.decision_engine import DecisionEngine
from src.memory.memory_manager import MemoryManager
from src.mission.department import detect_mission_type, detect_research_loop_intent


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
        self.last_mission = None
        self.last_provider_route = None

    def chat(self, message: str, execution_hints: dict | None = None) -> str:
        message = message.strip()
        self.last_mission = None
        self.last_provider_route = None

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

        # Sprint 37: AUTONOMOUS RESEARCH LOOP -- "daha iyi ol"/"kendini
        # geliştir" gibi açık self-improvement sinyali taşıyan istekler,
        # tek seferlik Mission YERİNE (loop niyeti zaten bir Mission
        # sinyali GEREKTİRİR, bkz. ``detect_research_loop_intent``)
        # sınırlı-turlu bir araştırma döngüsüyle çalıştırılır. Bu kontrol
        # ``_requires_mission``'DAN ÖNCE gelir; diğer TÜM Mission istekleri
        # (297 mevcut test) eskisi gibi tek-seferlik kalır.
        if self._requires_research_loop(message):
            return self._run_research_loop(message)

        if self._requires_mission(message):
            return self._run_mission(message, execution_hints=execution_hints)

        result = self.workflow.run(message)
        chat_worker = self.agent_router.registry.get("chat")
        self.last_provider_route = getattr(chat_worker, "last_route", None)
        if self.last_provider_route is not None and not self.last_provider_route.success:
            raise RuntimeError(
                "All configured providers failed: "
                + " -> ".join(self.last_provider_route.attempted_providers)
            )
        return result

    @staticmethod
    def _requires_mission(message: str) -> bool:
        """Mesaj, mevcut Mission sınıflandırıcısının (``src.mission``)
        tanıdığı en az bir alan-özel sinyal içeriyorsa ``True``. Düz
        sohbet ("Merhaba" gibi) hiçbir sinyalle eşleşmez → ``False`` →
        eski ``WorkflowEngine`` akışı BOZULMADAN devam eder."""

        return detect_mission_type(message) is not None

    @staticmethod
    def _requires_research_loop(message: str) -> bool:
        """bkz. ``src.mission.department.detect_research_loop_intent`` --
        yalnızca AÇIK bir self-improvement sinyali VE bir Mission sinyali
        birlikte varsa ``True``."""

        return detect_research_loop_intent(message)

    def _run_research_loop(self, message: str) -> str:
        """Sprint 37: Mission → TaskPlan → PlanExecutor zincirini (Sprint
        13-36, DEĞİŞTİRİLMEDİ) sınırlı sayıda tur çalıştırır (bkz.
        ``CEO.run_research_loop``), sonucu ``CEO.build_research_loop_report``
        ile okunabilir bir rapora çevirir."""

        result = self.ceo.run_research_loop(message)
        return self.ceo.build_research_loop_report(result)

    def _run_mission(self, message: str, execution_hints: dict | None = None) -> str:
        """Mission → TaskPlan → PlanExecutor → Execution zincirini
        (Sprint 13, DEĞİŞTİRİLMEDİ) CANLI olarak çalıştırır; sonucu
        Sprint 16'nın CEO Report Engine'i (``CEO.build_report`` ->
        ``src.mission.report_builder``) ile okunabilir bir CEO raporuna
        çevirir -- departmanların GERÇEK bulguları (GitHub/Evaluation/
        Sandbox/Integration) artık kullanıcıya YANSITILIR, yalnızca
        durum sayaçları değil."""

        mission, _plan, _report = self.ceo.run_mission(message, execution_hints=execution_hints)
        self.last_mission = mission
        return self.ceo.build_report(mission)

    def remember(self, key, value):
        self.memory.save(key, value)

    def recall(self, key):
        return self.memory.load(key)
