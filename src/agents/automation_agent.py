from src.agents.base_agent import BaseAgent
from src.automation.manager import AutomationManager
from src.planner.task import Task


class AutomationAgent(BaseAgent):
    """``automation`` departmanını (Sprint 39) ``AutomationManager``'a
    bağlar. Tamamen deterministik (LLM çağrısı YOK) -- yalnızca bir
    yayın-öncesi kontrol listesi üretir, hiçbir şeyi ÇALIŞTIRMAZ/
    ZAMANLAMAZ/YAYINLAMAZ."""

    def __init__(self) -> None:
        super().__init__("Automation Agent")
        self.manager = AutomationManager()

    def execute(self, task: Task) -> str:
        topic = str(getattr(task, "target", ""))
        return self.manager.plan(topic=topic)
