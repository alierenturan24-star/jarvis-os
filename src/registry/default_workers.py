from src.agents.browser_agent import BrowserAgent
from src.agents.chat_agent import ChatAgent
from src.agents.coding_agent import CodingAgent
from src.agents.evolution_agent import EvolutionAgent
from src.agents.finance_agent import FinanceAgent
from src.agents.opportunity_agent import OpportunityAgent
from src.agents.planning_agent import PlanningAgent
from src.agents.research_agent import ResearchAgent
from src.registry.worker_registry import WorkerRegistry


def build_default_worker_registry() -> WorkerRegistry:
    """JARVIS'in varsayılan çalışan kayıtlarını oluşturur."""

    registry = WorkerRegistry()

    registry.register(
        name="browser",
        worker=BrowserAgent(),
        capabilities={"browser", "open_site", "web_navigation"},
        aliases={"tarayıcı"},
    )
    registry.register(
        name="research",
        worker=ResearchAgent(),
        capabilities={"research", "news", "web_research"},
        aliases={"araştırma"},
    )
    registry.register(
        name="opportunity",
        worker=OpportunityAgent(),
        capabilities={"opportunity", "income_ideas", "ai_tools"},
        aliases={"fırsat"},
    )
    registry.register(
        name="finance",
        worker=FinanceAgent(),
        capabilities={"finance", "market", "risk_analysis"},
        aliases={"finans"},
    )
    registry.register(
        name="evolution",
        worker=EvolutionAgent(),
        capabilities={"evolution", "self_improvement", "tool_discovery"},
        aliases={"gelişim"},
    )
    registry.register(
        name="chat",
        worker=ChatAgent(),
        capabilities={"chat", "general"},
        aliases={"sohbet"},
    )
    registry.register(
        name="coding",
        worker=CodingAgent(),
        capabilities={"coding", "debug", "software"},
        aliases={"kodlama"},
    )
    registry.register(
        name="planning",
        worker=PlanningAgent(),
        capabilities={"planning", "task_breakdown"},
        aliases={"planlama"},
    )

    return registry
