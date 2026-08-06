from __future__ import annotations

from src.config.settings import Settings
from src.providers.provider_manager import ProviderManager


class ModelRouter:
    """Tüm dil modeli sağlayıcılarını tek arayüzden çalıştırır.

    Gerçek sağlayıcı seçimi ve HTTP çağrıları ``ProviderManager`` ve
    ``src/providers/*_provider.py`` sınıflarına devredilmiştir; bu sınıf
    eski çağıranlar için geriye dönük uyumlu ince bir katmandır.
    """

    PROVIDER_ALIASES = ProviderManager.ALIASES

    def __init__(self) -> None:
        self.provider = Settings.DEFAULT_PROVIDER
        self.manager = ProviderManager()

        # Doğrudan .ollama / .aiml okuyan eski koda geriye dönük uyumluluk.
        self.ollama = self.manager.get("ollama")
        self.aiml = self.manager.get("aiml")

    def set_provider(self, provider: str) -> None:
        self.provider = self._normalize_provider(provider)

    def generate(
        self,
        prompt: str,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            return "Model için boş komut gönderildi."

        provider = provider_name or self.provider
        return self.manager.generate(prompt.strip(), provider, model_name)

    @staticmethod
    def _normalize_provider(provider: str) -> str:
        return ProviderManager.normalize(provider)
