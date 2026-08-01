from src.agents.base_agent import BaseAgent


class MemoryAgent(BaseAgent):

    def __init__(self):
        super().__init__("Memory Agent")

    def can_handle(self, message: str) -> bool:

        keywords = [
            "benim adım",
            "beni hatırla",
            "unutma",
            "hatırla",
        ]

        message = message.lower()

        return any(word in message for word in keywords)

    def execute(self, message: str):

        return None