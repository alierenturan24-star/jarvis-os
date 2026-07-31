import subprocess

from src.config.settings import Settings
from src.providers.base_provider import BaseProvider


class OllamaProvider(BaseProvider):

    def __init__(self):
        super().__init__("Ollama")

    def generate(self, prompt: str) -> str:

        result = subprocess.run(
            [
                "ollama",
                "run",
                Settings.MODEL,
                prompt,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        return result.stdout.strip()