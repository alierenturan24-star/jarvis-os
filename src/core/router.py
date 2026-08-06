from src.core.agent_router import AgentRouter
from src.core.ceo import CEO


class CoreRouter:
    """CEO yönlendirmesi ile ajan yürütmesini bir arada sunan eski uyumluluk katmanı."""

    def __init__(self) -> None:
        self.ceo = CEO()
        self.agent_router = AgentRouter()

    def route(self, message: str):
        return self.ceo.choose_department(message)

    def execute(self, task):
        return self.agent_router.execute(task)
