from src.agents.base_agent import BaseAgent
from src.evolution.manager import EvolutionManager
from src.planner.task import Task


class EvolutionAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("Evolution Agent")
        self.manager = EvolutionManager()

    @staticmethod
    def _clean_focus(message: str) -> str:
        text = message.casefold().strip()
        phrases = [
            "kendini geliştirmek için araştır",
            "kendini geliştirmek için tara",
            "jarvis'i geliştirecek araçları bul",
            "jarvisi geliştirecek araçları bul",
            "gelişim fırsatlarını tara",
            "yeni araçları öğren",
            "merak taraması yap",
            "kendini geliştir",
        ]
        for phrase in phrases:
            text = text.replace(phrase, "")
        return text.strip(" :,-")

    def execute(self, task: Task) -> str:
        message = str(getattr(task, "target", ""))
        focus = self._clean_focus(message)
        return self.manager.scan(focus=focus)
