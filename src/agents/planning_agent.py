from src.agents.base_agent import BaseAgent
from src.planner.task import Task
from src.providers.router import ModelRouter


class PlanningAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("Planning Agent")
        self.router = ModelRouter()

    def health(self) -> dict:
        return {
            "agent": self.name,
            "available": True,
            "providers": self.router.manager.available_names(),
        }

    def execute(self, task: Task) -> str:
        prompt = f"""
Sen JARVIS Planning Agent'sın.
Her zaman Türkçe konuş.
Görevi kısa, sıralı, uygulanabilir adımlara ayır.
Gereksiz ayrıntı verme.

Görev: {task.target}
"""
        return self.router.generate(prompt=prompt, provider_name="ollama")
