from __future__ import annotations

from src.config.settings import Settings
from src.providers.openai_compatible_provider import OpenAICompatibleProvider


class GroqProvider(OpenAICompatibleProvider):
    def __init__(self) -> None:
        super().__init__(
            "groq",
            label="Groq",
            api_key=Settings.GROQ_API_KEY,
            base_url=Settings.GROQ_BASE_URL,
            default_model=Settings.GROQ_MODEL,
            timeout=Settings.REQUEST_TIMEOUT,
        )
