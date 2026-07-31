from src.agents.base_agent import BaseAgent


class ChatAgent(BaseAgent):

    def __init__(self):
        super().__init__("Chat Agent")

    def can_handle(self, message: str) -> bool:
        return True

    def build_instruction(self) -> str:

        return """
Bu normal sohbet görevidir.

Doğal konuş.

Kısa cevap ver.

Kod üretme.
"""