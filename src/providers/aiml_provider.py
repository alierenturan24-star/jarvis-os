import requests

from src.config.settings import Settings
from src.providers.base_provider import BaseProvider


class AIMLProvider(BaseProvider):

    def __init__(self) -> None:
        super().__init__("aiml")

    def generate(self, prompt: str, model: str | None = None) -> str:

        model = model or Settings.AIML_DEFAULT_MODEL

        headers = {
            "Authorization": f"Bearer {Settings.AIML_API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": 0.3,
        }

        try:

            response = requests.post(
                f"{Settings.AIML_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=Settings.AIML_TIMEOUT,
            )

            response.raise_for_status()

            data = response.json()

            return data["choices"][0]["message"]["content"]

        except Exception as error:

            return f"AIML API hatası: {error}"