from src.providers.router import ModelRouter


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

        return self.router.generate(
            prompt=prompt,
            provider_name=provider
        )

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