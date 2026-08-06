from src.agents.base_agent import BaseAgent
from src.planner.task import Task
from src.providers.router import ModelRouter


class CodingAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("Coding Agent")
        self.router = ModelRouter()

    def health(self) -> dict:
        return {
            "agent": self.name,
            "available": True,
            "providers": self.router.manager.available_names(),
        }

    def execute(self, task: Task) -> str:
        prompt = f"""
Sen JARVIS Coding Agent'sın.
Her zaman Türkçe konuş.
İstenen kod görevini analiz et; güvenli, temiz ve uygulanabilir cevap ver.
Kullanıcı tam dosya istiyorsa parça parça kod verme.

Görev: {task.target}
"""
        return self.router.generate(prompt=prompt, provider_name="ollama")
