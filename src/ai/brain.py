from src.providers.router import ModelRouter
from src.providers.provider_manager import TASK_SHORT_CHAT


class Brain:

    def __init__(self):
        self.router = ModelRouter()

    def think(
        self,
        prompt: str,
        provider: str = None
    ):
        """
        İstenen modele soruyu gönderir.
        Provider verilmezse varsayılan modeli kullanır.
        """

        self.last_route = self.router.manager.route_and_generate(
            prompt, task_type=TASK_SHORT_CHAT, preferred_provider=provider,
        )
        return self.last_route.output

    def ask_openai(self, prompt):
        return self.think(prompt, "openai")

    def ask_claude(self, prompt):
        return self.think(prompt, "anthropic")

    def ask_gemini(self, prompt):
        return self.think(prompt, "gemini")

    def ask_deepseek(self, prompt):
        return self.think(prompt, "deepseek")

    def ask_groq(self, prompt):
        return self.think(prompt, "groq")

    def ask_aiml(self, prompt):
        return self.think(prompt, "aiml")
