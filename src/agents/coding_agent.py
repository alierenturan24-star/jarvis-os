from src.agents.base_agent import BaseAgent


class CodingAgent(BaseAgent):

    def __init__(self):
        super().__init__("Coding Agent")

    def can_handle(self, message: str) -> bool:

        keywords = [
            "python",
            "kod",
            "program",
            "hata",
            "debug",
        ]

        message = message.lower()

        return any(word in message for word in keywords)

    def execute(self, message: str):

        return None