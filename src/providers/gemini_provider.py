from __future__ import annotations

from typing import Any

import requests

from src.config.settings import Settings
from src.providers.base_provider import BaseProvider


class GeminiProvider(BaseProvider):
    """Google Gemini sağlayıcısı."""

    def __init__(self) -> None:
        super().__init__("gemini")

    def is_available(self) -> bool:
        return bool(Settings.GEMINI_API_KEY)

    def generate(self, prompt: str, model: str | None = None) -> str:
        if not Settings.GEMINI_API_KEY:
            return (
                "Gemini API anahtarı tanımlı değil. "
                "Anahtarı .env dosyasına ekle."
            )

        model = model or Settings.GEMINI_MODEL
        response = requests.post(
            (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={Settings.GEMINI_API_KEY}"
            ),
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3},
            },
            timeout=Settings.REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return "Gemini boş cevap verdi."
        parts = candidates[0].get("content", {}).get("parts", [])
        texts = [str(part.get("text", "")).strip() for part in parts if isinstance(part, dict)]
        return "\n".join(text for text in texts if text) or "Gemini boş cevap verdi."
