from src.providers.base_provider import BaseProvider


class MockProvider(BaseProvider):
    def __init__(self):
        super().__init__("Mock Provider")

    def generate(self, prompt: str) -> str:
        return f"[{self.name}] Görev alındı: {prompt}"