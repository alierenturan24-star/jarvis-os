from __future__ import annotations

from src.config.settings import Settings
from src.providers.openai_compatible_provider import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(self) -> None:
        super().__init__(
            "deepseek",
            label="DeepSeek",
            api_key=Settings.DEEPSEEK_API_KEY,
            base_url=Settings.DEEPSEEK_BASE_URL,
            default_model=Settings.DEEPSEEK_MODEL,
            timeout=Settings.REQUEST_TIMEOUT,
        )
