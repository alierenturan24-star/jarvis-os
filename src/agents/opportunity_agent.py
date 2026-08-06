from src.agents.base_agent import BaseAgent
from src.opportunity.manager import OpportunityManager
from src.planner.task import Task


class OpportunityAgent(BaseAgent):

    def __init__(self) -> None:
        super().__init__("Opportunity Agent")
        self.manager = OpportunityManager()

    @staticmethod
    def _clean_topic(message: str) -> str:

        text = message.casefold().strip()

        phrases = [
            "fırsatları araştır",
            "fırsat araştır",
            "fırsatları bul",
            "fırsat bul",
            "para kazanma fikirlerini bul",
            "gelir fırsatlarını bul",
            "yeni ai fırsatlarını bul",
        ]

        for phrase in phrases:
            text = text.replace(
                phrase,
                "",
            )

        return text.strip(" :,-")

    def execute(self, task: Task) -> str:

        message = str(
            getattr(task, "target", "")
        )

        topic = self._clean_topic(message)

        return self.manager.scan(topic)