from __future__ import annotations

from src.config.settings import Settings
from src.council.models import ModelProfile
from src.providers.provider_manager import ProviderManager


class CouncilRegistry:
    """AI Konseyi'nin bildiği modelleri ve görev tipine göre öncelik
    sıralamasını tutar.

    Aktiflik durumu artık sabit değil: ``ProviderManager`` üzerinden ilgili
    sağlayıcının gerçekten kullanılabilir olup olmadığına (API anahtarı
    tanımlı mı / yerel model erişilebilir mi) bakılarak dinamik hesaplanır.
    """

    # Görev tipi -> öncelik sırasına göre provider anahtarları.
    TASK_PROVIDER_MAP: dict[str, list[str]] = {
        "coding": ["claude", "deepseek"],
        "research": ["gemini", "claude"],
        "finance": ["openai", "claude", "deepseek"],
        "general": ["aiml", "ollama_local"],
    }

    def __init__(self) -> None:
        self.provider_manager = ProviderManager()

        self.models: dict[str, ModelProfile] = {
            "ollama_local": ModelProfile(
                name="Ollama Local",
                provider="ollama",
                model=Settings.CHAT_MODEL,
                strengths=["chat", "privacy", "local", "general"],
                local=True,
                cost_score=100,
                speed_score=65,
                quality_score=65,
                priority=50,
            ),
            "aiml": ModelProfile(
                name="AIML",
                provider="aiml",
                model=Settings.AIML_DEFAULT_MODEL,
                strengths=["general", "chat", "cost_efficient"],
                local=False,
                cost_score=75,
                speed_score=70,
                quality_score=70,
                priority=60,
            ),
            "deepseek": ModelProfile(
                name="DeepSeek",
                provider="deepseek",
                model=Settings.DEEPSEEK_MODEL,
                strengths=["coding", "math", "reasoning", "finance"],
                local=False,
                cost_score=80,
                speed_score=70,
                quality_score=86,
                priority=70,
            ),
            "gemini": ModelProfile(
                name="Gemini",
                provider="gemini",
                model=Settings.GEMINI_MODEL,
                strengths=["research", "multimodal", "analysis", "content"],
                local=False,
                cost_score=60,
                speed_score=80,
                quality_score=88,
                priority=75,
            ),
            "openai": ModelProfile(
                name="OpenAI",
                provider="openai",
                model=Settings.OPENAI_MODEL,
                strengths=["reasoning", "finance", "tools", "general"],
                local=False,
                cost_score=45,
                speed_score=75,
                quality_score=95,
                priority=80,
            ),
            "claude": ModelProfile(
                name="Claude",
                provider="claude",
                model=Settings.ANTHROPIC_MODEL,
                strengths=["coding", "reasoning", "writing", "analysis"],
                local=False,
                cost_score=45,
                speed_score=70,
                quality_score=95,
                priority=85,
            ),
        }

        self.refresh_availability()

    def refresh_availability(self) -> None:
        """Her modelin ``enabled`` durumunu ilgili sağlayıcının gerçek
        kullanılabilirliğine göre yeniden hesaplar (API anahtarı olmayan
        sağlayıcılar otomatik pasif hale gelir)."""
        for profile in self.models.values():
            provider = self.provider_manager.get(profile.provider)
            profile.enabled = bool(provider) and provider.is_available()

    def enabled_models(self) -> list[ModelProfile]:
        return [profile for profile in self.models.values() if profile.enabled]

    def profiles_for_task(self, task_type: str) -> list[ModelProfile]:
        """Görev tipine göre öncelik sırasındaki AKTİF profilleri döndürür."""
        keys = self.TASK_PROVIDER_MAP.get(task_type, self.TASK_PROVIDER_MAP["general"])

        result = []
        for key in keys:
            profile = self.models.get(key)
            if profile is not None and profile.enabled:
                result.append(profile)
        return result

    def get(self, name: str) -> ModelProfile | None:
        return self.models.get(name)

    def enable(self, name: str) -> bool:
        profile = self.get(name)

        if profile is None:
            return False

        profile.enabled = True
        return True

    def disable(self, name: str) -> bool:
        profile = self.get(name)

        if profile is None:
            return False

        profile.enabled = False
        return True
