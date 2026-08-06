from __future__ import annotations

from src.config.settings import Settings
from src.providers.openai_compatible_provider import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self) -> None:
        super().__init__(
            "openrouter",
            label="OpenRouter",
            api_key=Settings.OPENROUTER_API_KEY,
            base_url=Settings.OPENROUTER_BASE_URL,
            default_model=Settings.OPENROUTER_MODEL,
            timeout=Settings.REQUEST_TIMEOUT,
            extra_headers={
                "HTTP-Referer": "https://localhost/jarvis-os",
                "X-Title": Settings.APP_NAME,
            },
        )
