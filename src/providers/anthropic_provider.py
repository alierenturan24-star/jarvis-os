from __future__ import annotations

from typing import Any

import requests

from src.config.settings import Settings
from src.providers.base_provider import BaseProvider


class AnthropicProvider(BaseProvider):
    """Claude (Anthropic Messages API) sağlayıcısı."""

    def __init__(self) -> None:
        super().__init__("anthropic")

    def is_available(self) -> bool:
        return bool(Settings.ANTHROPIC_API_KEY)

    def generate(self, prompt: str, model: str | None = None) -> str:
        if not Settings.ANTHROPIC_API_KEY:
            return (
                "Anthropic API anahtarı tanımlı değil. "
                "Anahtarı .env dosyasına ekle."
            )

        response = requests.post(
            f"{Settings.ANTHROPIC_BASE_URL}/messages",
            headers={
                "x-api-key": Settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": model or Settings.ANTHROPIC_MODEL,
                "max_tokens": 2048,
                "temperature": 0.3,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=Settings.REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        blocks = data.get("content", [])
        text_parts = [
            str(block.get("text", "")).strip()
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(part for part in text_parts if part) or "Anthropic boş cevap verdi."
