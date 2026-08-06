from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on", "evet"}


def _clean_env_value(name: str, value: str) -> str:
    """.env içine yanlışlıkla ``KEY=KEY=value`` şeklinde yazılmış değerleri temizler."""
    cleaned = value.strip().strip('"').strip("'")
    prefix = f"{name}="
    while cleaned.startswith(prefix):
        cleaned = cleaned[len(prefix):].strip().strip('"').strip("'")
    return cleaned


class Settings:
    """JARVIS genel ayarları.

    Eski modüllerin kullandığı ``Settings.X`` yapısını korur. Aynı zamanda
    yeni provider katmanının gerektirdiği bütün API ve model ayarlarını tek
    yerde toplar.
    """

    APP_NAME = os.getenv("APP_NAME", "JARVIS")
    VERSION = os.getenv("JARVIS_VERSION", "0.5.1")
    LANGUAGE = os.getenv("LANGUAGE", "Türkçe")
    DEBUG = _env_bool("DEBUG", False)

    DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "ollama").strip().lower()

    # Yerel Ollama
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    OLLAMA_MODEL = _clean_env_value(
        "OLLAMA_MODEL", os.getenv("OLLAMA_MODEL", "llama3.2:latest")
    )
    OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "240"))

    # Eski modüllerle geriye dönük uyumluluk
    MODEL = OLLAMA_MODEL
    CHAT_MODEL = os.getenv("CHAT_MODEL", OLLAMA_MODEL)

    # AIML API
    AIML_API_KEY = os.getenv("AIML_API_KEY", "").strip()
    AIML_BASE_URL = os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1").rstrip("/")
    AIML_DEFAULT_MODEL = os.getenv("AIML_MODEL", "openai/gpt-4.1-mini")
    AIML_TIMEOUT = int(os.getenv("AIML_TIMEOUT", "120"))

    # OpenAI
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    # Anthropic / Claude
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
    ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    # Google Gemini
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # DeepSeek
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # Groq
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
    GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # OpenRouter
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
    OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")

    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))
    MEMORY_FILE = os.getenv("MEMORY_FILE", str(PROJECT_ROOT / "memory.json"))
    MAX_MEMORY = int(os.getenv("MAX_MEMORY", "20"))


# Düz değişken import eden yeni modüller için uyumluluk takma adları.
DEFAULT_PROVIDER = Settings.DEFAULT_PROVIDER
AIML_API_KEY = Settings.AIML_API_KEY
AIML_MODEL = Settings.AIML_DEFAULT_MODEL
OPENAI_API_KEY = Settings.OPENAI_API_KEY
OPENAI_MODEL = Settings.OPENAI_MODEL
ANTHROPIC_API_KEY = Settings.ANTHROPIC_API_KEY
ANTHROPIC_MODEL = Settings.ANTHROPIC_MODEL
GEMINI_API_KEY = Settings.GEMINI_API_KEY
GEMINI_MODEL = Settings.GEMINI_MODEL
DEEPSEEK_API_KEY = Settings.DEEPSEEK_API_KEY
DEEPSEEK_MODEL = Settings.DEEPSEEK_MODEL
GROQ_API_KEY = Settings.GROQ_API_KEY
GROQ_MODEL = Settings.GROQ_MODEL
OPENROUTER_API_KEY = Settings.OPENROUTER_API_KEY
MEMORY_FILE = Settings.MEMORY_FILE
MAX_MEMORY = Settings.MAX_MEMORY
DEBUG = Settings.DEBUG
