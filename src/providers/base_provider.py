from __future__ import annotations

from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """Tüm LLM sağlayıcılarının uyması gereken ortak arayüz."""

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def generate(self, prompt: str, model: str | None = None) -> str:
        """Verilen komuta cevap üretir."""
        raise NotImplementedError

    def is_available(self) -> bool:
        """Sağlayıcı çalışmaya hazır mı (ör. API anahtarı tanımlı mı)."""
        return True