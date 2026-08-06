from __future__ import annotations

from typing import Any

import requests

from src.providers.base_provider import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI'nin ``/chat/completions`` sözleşmesini kullanan sağlayıcılar
    (OpenAI, DeepSeek, Groq, OpenRouter, ...) için ortak taban sınıf."""

    def __init__(
        self,
        name: str,
        *,
        label: str,
        api_key: str,
        base_url: str,
        default_model: str,
        timeout: int,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(name)
        self.label = label
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str, model: str | None = None) -> str:
        if not self.api_key:
            return (
                f"{self.label} API anahtarı tanımlı değil. "
                "Anahtarı .env dosyasına ekle."
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.extra_headers)

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json={
                "model": model or self.default_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return str(data["choices"][0]["message"]["content"]).strip()
