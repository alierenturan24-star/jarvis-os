from src.intent.intent_router import IntentRouter
from src.core.tool_selector import ToolSelector
from src.providers.router import ModelRouter
from src.memory.conversation_memory import ConversationMemory

from src.agents.browser_agent import BrowserAgent


class Commander:

    def __init__(self):

        self.intent_router = IntentRouter()
        self.tool_selector = ToolSelector()

        self.browser_agent = BrowserAgent()

        self.router = ModelRouter()
        self.memory = ConversationMemory()

    def process(self, user_message):

        self.memory.add("Kullanıcı", user_message)

        intent = self.intent_router.detect(user_message)

        # Browser Agent
        if intent == "browser":

            result = self.browser_agent.execute(user_message)

            self.memory.add("Jarvis", result)

            return result

        history = self.memory.build_prompt()

        prompt = f"""
Sen JARVIS adlı kişisel yapay zekâ asistansın.

Her zaman Türkçe konuş.

Geçmiş konuşmalar:

{history}

Kullanıcı:

{user_message}

Cevap:
"""

        response = self.router.generate(
            prompt=prompt,
            provider_name="ollama",
        )

        self.memory.add("Jarvis", response)

        return response