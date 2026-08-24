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


def _env_float(
    name: str, default: float, *, minimum: float | None = None, maximum: float | None = None,
) -> float:
    """Safe float env parser -- FAILS CLOSED to ``default``, never raises.

    Diğer ayarların çıplak ``int(os.getenv(...))`` deseninden BİLEREK
    farklı: malformed (``"abc"``), boş, NaN/sonsuz veya [minimum, maximum]
    dışı bir değer verildiğinde sessizce ``default``'a düşer -- bozuk bir
    ortam değişkeni asla süreci çökertmez ve asla sınırsız/aşırı bir değere
    izin vermez (bkz. ``CLAUDE_CODE_TIMEOUT_SECONDS`` -- bir subprocess
    timeout'unun sınırsız kalması KABUL EDİLEMEZ)."""

    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = float(raw.strip())
    except (TypeError, ValueError):
        return default
    if parsed != parsed or parsed in (float("inf"), float("-inf")):  # NaN/inf guard
        return default
    if minimum is not None and parsed < minimum:
        return default
    if maximum is not None and parsed > maximum:
        return default
    return parsed


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
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

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

    # Sprint 37: Autonomous Research Loop -- hiçbir yerde bugüne kadar bir
    # "tur sayısı" üst sınırı yoktu (bkz. Sprint 37 araştırması). Tek round
    # içindeki işler zaten Task.timeout_seconds/DEPARTMENT_TASK_TIMEOUT_SECONDS
    # ile sınırlı -- bu ikisi yalnızca "kaç tur" ve "toplam ne kadar sürede"
    # sorularının üst sınırıdır (sonsuz döngü KESİNLİKLE olmasın kuralı).
    RESEARCH_LOOP_MAX_ROUNDS = int(os.getenv("RESEARCH_LOOP_MAX_ROUNDS", "3"))
    RESEARCH_LOOP_MAX_SECONDS = int(os.getenv("RESEARCH_LOOP_MAX_SECONDS", "900"))
    RESEARCH_MAX_SOURCES_PER_CYCLE = int(os.getenv("RESEARCH_MAX_SOURCES_PER_CYCLE", "8"))
    RESEARCH_MAX_FINDINGS_PER_CYCLE = int(os.getenv("RESEARCH_MAX_FINDINGS_PER_CYCLE", "20"))
    RESEARCH_MIN_INTERVAL_SECONDS = int(os.getenv("RESEARCH_MIN_INTERVAL_SECONDS", "3600"))
    RESEARCH_MAX_CONSECUTIVE_FAILURES = int(os.getenv("RESEARCH_MAX_CONSECUTIVE_FAILURES", "5"))
    RESEARCH_CYCLE_MAX_SECONDS = float(os.getenv("RESEARCH_CYCLE_MAX_SECONDS", "120"))
    CAPABILITY_VERIFICATION_MAX_AGE_SECONDS = int(os.getenv("CAPABILITY_VERIFICATION_MAX_AGE_SECONDS", "2592000"))

    # Claude Code CLI (``--permission-mode plan``, salt-okunur repository
    # inceleme) subprocess timeout'u. Sprint 44'ün orijinal 60 sn varsayılanı
    # kısa promptlar için ayarlanmıştı; 2026-08-23 canlı smoke testi, gerçek
    # bir "bu dosyayı ve kalite kapılarını açıkla" analitik promptunun plan
    # modunda (kalıcı bir indeks YOK -- her çağrı bağlamı kendi Read/Glob/
    # Grep araç çağrılarıyla yeniden türetir) daha fazla duvar-saati süresine
    # ihtiyaç duyduğunu KANITLADI (tam 60.05 sn'de ``TimeoutExpired``).
    # Yapılandırılabilir ama SINIRLI -- [30, 600] sn dışı veya bozuk bir
    # değer sessizce 180 sn varsayılana düşer, ASLA sınırsız beklemeye değil.
    CLAUDE_CODE_TIMEOUT_SECONDS = _env_float(
        "CLAUDE_CODE_TIMEOUT_SECONDS", 180.0, minimum=30.0, maximum=600.0,
    )

    # Sprint: research/production pipeline audit -- research timeout fix. A
    # real Swiss Insider mission run failed with "Task timed out (20.0 sec)"
    # during research. Root cause: mission/recovery.py's same-method retry
    # step unconditionally shrank the retry's budget to a flat 20s -- smaller
    # than even ONE inner web-search call's own timeout, guaranteeing a
    # second, faster failure for any genuinely slow-but-correct research
    # call. This is the INNER per-web-search-call timeout (WebSearchTool/
    # ResearchCollector) -- configurable but bounded like
    # CLAUDE_CODE_TIMEOUT_SECONDS above: a malformed/absurd value never
    # hangs a network call forever, and never grows large enough to threaten
    # the outer department budget on its own (see
    # RESEARCH_DEPARTMENT_TASK_TIMEOUT_SECONDS in department_orchestrator.py,
    # which is sized FROM this value -- same inner-then-outer invariant as
    # CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS).
    RESEARCH_PROVIDER_TIMEOUT_SECONDS = _env_float(
        "RESEARCH_PROVIDER_TIMEOUT_SECONDS", 15.0, minimum=5.0, maximum=45.0,
    )

    # The same-method retry window recovery.py uses after a genuine TIMEOUT
    # failure. Must never be smaller than a department's own real inner
    # needs (that was the bug -- a flat 20s cap). Defaults large enough that
    # it never binds below any configured department outer timeout (i.e. no
    # shrink in practice); still configurable/bounded, fails closed to the
    # default on malformed input, so an operator CAN tighten it deliberately
    # without risking an unbounded/invalid wait.
    RECOVERY_SAME_METHOD_RETRY_TIMEOUT_SECONDS = _env_float(
        "RECOVERY_SAME_METHOD_RETRY_TIMEOUT_SECONDS", 300.0, minimum=15.0, maximum=600.0,
    )


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
