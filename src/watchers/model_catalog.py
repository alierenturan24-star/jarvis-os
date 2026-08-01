from dataclasses import dataclass, field


@dataclass
class WatchedProvider:
    provider_id: str
    name: str
    category: str
    official_sources: list[str]
    keywords: list[str] = field(default_factory=list)
    enabled: bool = True
    priority: int = 50


class ModelCatalog:
    """
    JARVIS'in takip edeceği yapay zekâ sağlayıcılarını,
    kodlama ajanlarını ve model ekosistemlerini tanımlar.
    """

    def __init__(self) -> None:
        self.providers = {
            "openai_codex": WatchedProvider(
                provider_id="openai_codex",
                name="OpenAI Codex",
                category="coding_agent",
                official_sources=[
                    "https://openai.com/codex/",
                    "https://developers.openai.com/codex/changelog",
                    "https://github.com/openai/codex/releases",
                    "https://github.com/openai/skills",
                ],
                keywords=[
                    "codex",
                    "codex cli",
                    "codex app",
                    "codex skill",
                    "codex plugin",
                ],
                priority=100,
            ),
            "claude_code": WatchedProvider(
                provider_id="claude_code",
                name="Claude Code",
                category="coding_agent",
                official_sources=[
                    "https://docs.anthropic.com/",
                    "https://github.com/anthropics",
                ],
                keywords=[
                    "claude code",
                    "claude skill",
                    "claude mcp",
                    "anthropic model",
                ],
                priority=100,
            ),
            "qwen": WatchedProvider(
                provider_id="qwen",
                name="Qwen ve Qwen Code",
                category="model_and_coding_agent",
                official_sources=[
                    "https://qwenlm.github.io/",
                    "https://qwenlm.github.io/qwen-code-docs/",
                ],
                keywords=[
                    "qwen",
                    "qwen code",
                    "qwen coder",
                    "qwen model",
                    "qwen skill",
                ],
                priority=95,
            ),
            "deepseek": WatchedProvider(
                provider_id="deepseek",
                name="DeepSeek",
                category="model_provider",
                official_sources=[
                    "https://api-docs.deepseek.com/",
                    "https://api-docs.deepseek.com/updates/",
                ],
                keywords=[
                    "deepseek",
                    "deepseek v4",
                    "deepseek coder",
                    "deepseek api",
                ],
                priority=95,
            ),
            "nvidia_nim": WatchedProvider(
                provider_id="nvidia_nim",
                name="NVIDIA NIM",
                category="model_provider",
                official_sources=[
                    "https://build.nvidia.com/",
                    "https://docs.api.nvidia.com/",
                ],
                keywords=[
                    "nvidia nim",
                    "free api",
                    "developer api",
                    "new model",
                ],
                priority=95,
            ),
            "ollama": WatchedProvider(
                provider_id="ollama",
                name="Ollama",
                category="local_model_runtime",
                official_sources=[
                    "https://ollama.com/library",
                    "https://github.com/ollama/ollama/releases",
                ],
                keywords=[
                    "ollama",
                    "new model",
                    "local model",
                ],
                priority=90,
            ),
            "openrouter": WatchedProvider(
                provider_id="openrouter",
                name="OpenRouter",
                category="model_router",
                official_sources=[
                    "https://openrouter.ai/models",
                ],
                keywords=[
                    "free model",
                    "new model",
                    "pricing",
                    "rate limit",
                ],
                priority=90,
            ),
            "google_gemini": WatchedProvider(
                provider_id="google_gemini",
                name="Google Gemini",
                category="model_provider",
                official_sources=[
                    "https://ai.google.dev/",
                ],
                keywords=[
                    "gemini",
                    "free tier",
                    "api quota",
                    "new model",
                ],
                priority=85,
            ),
            "groq": WatchedProvider(
                provider_id="groq",
                name="Groq",
                category="model_provider",
                official_sources=[
                    "https://console.groq.com/docs",
                ],
                keywords=[
                    "groq",
                    "free api",
                    "rate limit",
                    "new model",
                ],
                priority=80,
            ),
            "huggingface": WatchedProvider(
                provider_id="huggingface",
                name="Hugging Face",
                category="model_hub",
                official_sources=[
                    "https://huggingface.co/models",
                    "https://huggingface.co/docs",
                ],
                keywords=[
                    "new model",
                    "inference api",
                    "free tier",
                    "open source",
                ],
                priority=80,
            ),
        }

    def get(self, provider_id: str) -> WatchedProvider | None:
        return self.providers.get(provider_id)

    def enabled(self) -> list[WatchedProvider]:
        return sorted(
            (
                provider
                for provider in self.providers.values()
                if provider.enabled
            ),
            key=lambda provider: provider.priority,
            reverse=True,
        )

    def providers_for_project(
        self,
        project_type: str,
    ) -> list[WatchedProvider]:
        """
        Aktif otomasyona göre izleme önceliğini belirler.
        """

        project = project_type.lower()

        if "youtube" in project or "video" in project:
            preferred = {
                "qwen",
                "nvidia_nim",
                "ollama",
                "openrouter",
                "google_gemini",
                "huggingface",
            }

        elif "finans" in project or "borsa" in project:
            preferred = {
                "openai_codex",
                "claude_code",
                "deepseek",
                "openrouter",
                "groq",
            }

        elif "kod" in project or "github" in project:
            preferred = {
                "openai_codex",
                "claude_code",
                "qwen",
                "deepseek",
                "ollama",
            }

        else:
            return self.enabled()

        return sorted(
            (
                provider
                for provider_id, provider in self.providers.items()
                if provider_id in preferred and provider.enabled
            ),
            key=lambda provider: provider.priority,
            reverse=True,
        )