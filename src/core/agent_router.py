from src.agents.browser_agent import BrowserAgent
from src.agents.chat_agent import ChatAgent
from src.agents.coding_agent import CodingAgent
from src.agents.evolution_agent import EvolutionAgent
from src.agents.finance_agent import FinanceAgent
from src.agents.opportunity_agent import OpportunityAgent
from src.agents.planning_agent import PlanningAgent
from src.agents.research_agent import ResearchAgent
from src.planner.task import Task
from src.registry.worker_registry import WorkerRegistry


class AgentRouter:
    """Resolves workers through a capability registry and executes tasks."""

    def __init__(self) -> None:
        self.registry = WorkerRegistry()
        self._register_default_workers()

    def _register_default_workers(self) -> None:
        self.registry.register(
            "browser",
            BrowserAgent(),
            capabilities={"browser", "navigation", "open_site"},
            aliases={"web_browser"},
            priority=50,
        )
        self.registry.register(
            "research",
            ResearchAgent(),
            capabilities={"research", "web_search", "analysis"},
            aliases={"araştırma"},
            priority=70,
        )
        self.registry.register(
            "opportunity",
            OpportunityAgent(),
            capabilities={"opportunity", "income", "discovery"},
            aliases={"fırsat"},
            priority=65,
        )
        self.registry.register(
            "finance",
            FinanceAgent(),
            capabilities={"finance", "market", "risk"},
            aliases={"finans"},
            priority=75,
        )
        self.registry.register(
            "evolution",
            EvolutionAgent(),
            capabilities={"evolution", "improvement", "tool_discovery"},
            aliases={"gelişim"},
            priority=80,
        )
        self.registry.register(
            "chat",
            ChatAgent(),
            capabilities={"chat", "general"},
            aliases={"conversation"},
            priority=10,
        )
        self.registry.register(
            "coding",
            CodingAgent(),
            capabilities={"coding", "debug", "software"},
            aliases={"code"},
            priority=60,
        )
        self.registry.register(
            "planning",
            PlanningAgent(),
            capabilities={"planning", "strategy"},
            aliases={"plan"},
            priority=40,
        )

    def register_worker(
        self,
        name: str,
        worker,
        *,
        capabilities=(),
        aliases=(),
        priority: int = 0,
        replace: bool = False,
    ) -> None:
        self.registry.register(
            name,
            worker,
            capabilities=capabilities,
            aliases=aliases,
            priority=priority,
            replace=replace,
        )

    def execute(self, task: Task):
        worker = self.registry.get(task.agent)

        if worker is None:
            worker = self.registry.best(task.action)

        if worker is None:
            task.status = "failed"
            task.error = f"Worker bulunamadı: {task.agent}"
            return task.error

        try:
            task.status = "running"
            result = worker.execute(task)
            task.status = "completed"
            task.result = str(result)
            return task.result
        except Exception as error:
            task.status = "failed"
            task.error = str(error)
            return f"Görev sırasında hata oluştu:\n{error}"
