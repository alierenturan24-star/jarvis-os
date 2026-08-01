from dataclasses import dataclass


@dataclass
class ProviderInfo:
    name: str
    enabled: bool
    local: bool
    api_required: bool
    model: str


class ProviderRegistry:

    def __init__(self):

        self.providers = {
            "ollama": ProviderInfo(
                name="Ollama",
                enabled=True,
                local=True,
                api_required=False,
                model="llama3.2",
            ),

            "openai": ProviderInfo(
                name="OpenAI",
                enabled=False,
                local=False,
                api_required=True,
                model="gpt",
            ),

            "claude": ProviderInfo(
                name="Claude",
                enabled=False,
                local=False,
                api_required=True,
                model="claude",
            ),

            "gemini": ProviderInfo(
                name="Gemini",
                enabled=False,
                local=False,
                api_required=True,
                model="gemini",
            ),

            "groq": ProviderInfo(
                name="Groq",
                enabled=False,
                local=False,
                api_required=True,
                model="llama",
            ),

            "nvidia": ProviderInfo(
                name="NVIDIA NIM",
                enabled=False,
                local=False,
                api_required=True,
                model="nim",
            ),
        }

    def list(self):
        return self.providers

    def get(self, name):
        return self.providers.get(name)