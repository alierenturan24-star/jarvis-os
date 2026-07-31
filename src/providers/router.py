from src.providers.mock_provider import MockProvider
from src.providers.ollama_provider import OllamaProvider


class ModelRouter:
    def __init__(self):
        self.providers = {
            "mock": MockProvider(),
            "ollama": OllamaProvider(),
        }

    def get_provider(self, provider_name: str):
        provider = self.providers.get(provider_name)

        if provider is None:
            raise ValueError(
                f"Model sağlayıcısı bulunamadı: {provider_name}"
            )

        return provider

    def generate(
        self,
        prompt: str,
        provider_name: str = "mock",
    ) -> str:
        provider = self.get_provider(provider_name)
        return provider.generate(prompt)