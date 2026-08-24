from __future__ import annotations

from src.config.settings import Settings
from src.providers.gemini_provider import GeminiProvider
from src.providers.provider_manager import ProviderManager


class _Provider:
    def __init__(self, response="ok", available=True):
        self.response = response
        self.available = available
        self.calls = 0

    def is_available(self):
        return self.available

    def generate(self, prompt, model=None):
        self.calls += 1
        return self.response


def _manager(tmp_path, monkeypatch, **providers):
    monkeypatch.chdir(tmp_path)
    manager = ProviderManager()
    manager._providers = providers
    return manager


def test_gemini_available_and_generate_uses_configured_model(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        return _Response()

    monkeypatch.setattr(Settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(Settings, "GEMINI_MODEL", "gemini-flash-latest")
    monkeypatch.setattr("src.providers.gemini_provider.requests.post", fake_post)
    provider = GeminiProvider()

    assert provider.is_available() is True
    assert provider.generate("ping") == "ok"
    assert "gemini-flash-latest:generateContent" in captured["url"]


def test_coding_stays_codex(tmp_path, monkeypatch):
    manager = _manager(
        tmp_path, monkeypatch,
        codex=_Provider(), gemini=_Provider(), ollama=_Provider(),
    )
    result = manager.route_and_generate("debug this", task_type="coding")
    assert result.provider_used == "codex"


def test_simple_task_stays_ollama(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch, ollama=_Provider(), gemini=_Provider())
    result = manager.route_and_generate("hello", task_type="short_chat")
    assert result.provider_used == "ollama"


def test_research_selects_gemini(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch, ollama=_Provider(), gemini=_Provider())
    result = manager.route_and_generate("deep analysis", task_type="long_research")
    assert result.chosen_provider == "gemini"
    assert result.provider_used == "gemini"


def test_gemini_failure_uses_available_alternative_once_and_records_failure(tmp_path, monkeypatch):
    gemini = _Provider("gemini api hatası: boom")
    openrouter = _Provider("alternative")
    ollama = _Provider("local")
    unavailable_aiml = _Provider("must not run", available=False)
    manager = _manager(
        tmp_path, monkeypatch, gemini=gemini, openrouter=openrouter,
        aiml=unavailable_aiml, ollama=ollama,
    )

    result = manager.route_and_generate("research", task_type="long_research")

    assert result.provider_used == "openrouter"
    assert result.fallback_used is True
    assert gemini.calls == 1
    assert openrouter.calls == 1
    assert ollama.calls == 0
    assert unavailable_aiml.calls == 0
    attempts = manager.execution_history.recent()
    assert any(item["provider"] == "gemini" and item["success"] is False for item in attempts)


def test_aiml_remains_research_fallback_before_ollama(tmp_path, monkeypatch):
    manager = _manager(
        tmp_path, monkeypatch,
        gemini=_Provider("gemini api hatası: boom"),
        aiml=_Provider("aiml answer"), ollama=_Provider("local"),
    )
    result = manager.route_and_generate("research", task_type="long_research")
    assert result.provider_used == "aiml"
