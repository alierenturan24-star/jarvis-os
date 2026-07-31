from src.agents.base_agent import BaseAgent


class PlanningAgent(BaseAgent):

    def __init__(self):
        super().__init__("Planning Agent")

    def can_handle(self, message: str) -> bool:

        keywords = [
            "plan",
            "yapılacak",
            "takvim",
            "program",
        ]

        message = message.lower()

        return any(word in message for word in keywords)

    def execute(self, message: str):

        return None