from __future__ import annotations

from src.config.settings import Settings
from src.providers.openai_compatible_provider import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self) -> None:
        super().__init__(
            "openai",
            label="OpenAI",
            api_key=Settings.OPENAI_API_KEY,
            base_url=Settings.OPENAI_BASE_URL,
            default_model=Settings.OPENAI_MODEL,
            timeout=Settings.REQUEST_TIMEOUT,
        )
