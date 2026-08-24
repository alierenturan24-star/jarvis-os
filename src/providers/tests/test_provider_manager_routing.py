from __future__ import annotations

from src.providers.provider_manager import ProviderManager


class _FakeProvider:
    def __init__(self, available: bool = True, response: str | None = None) -> None:
        self._available = available
        # Gerçek provider'lar (ör. AnthropicProvider) anahtar/bağlantı
        # yokken bile ÇAĞRILIRSA (``_generate_for_route`` ``is_available()``
        # KONTROL ETMEZ, yalnızca ``generate()`` çağırır) bir hata metni
        # DÖNER, exception FIRLATMAZ -- bu sahte de AYNI şekilde davranır.
        self._response = response if response is not None else (
            "ok" if available else "api anahtarı tanımlı değil"
        )
        self.calls = 0

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, model: str | None = None) -> str:
        self.calls += 1
        return self._response


class TestRouteAndGenerateRecordsExecutionHistory:
    """Sprint 40 (LEARNING FROM EXECUTION): her ``route_and_generate``
    çağrısı, yeni bir router mimarisi İCAT EDİLMEDEN, mevcut
    ``RouteResult``'tan ``ProviderExecutionHistory``'e (ZATEN VAR olan
    KnowledgeBase deseniyle) kaydedilmeli."""

    def test_successful_call_is_recorded(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        manager._providers["ollama"] = _FakeProvider(available=True, response="gerçek cevap")

        result = manager.route_and_generate("prompt", task_type="short_chat")

        assert result.success is True
        assert result.fallback_used is False
        recent = manager.execution_history.recent()
        assert len(recent) == 1
        assert recent[0]["provider"] == "ollama"
        assert recent[0]["success"] is True
        assert recent[0]["task_type"] == "short_chat"

    def test_failed_then_fallback_records_the_provider_actually_used(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        manager._providers = {
            "aiml": _FakeProvider(available=True, response="aiml sağlayıcı hatası: boom"),
            "ollama": _FakeProvider(available=True, response="gerçek cevap"),
        }

        result = manager.route_and_generate("prompt", task_type="code", preferred_provider="aiml")

        assert result.fallback_used is True
        assert result.provider_used == "ollama"
        recent = manager.execution_history.recent()
        assert recent[0]["provider"] == "ollama"
        assert recent[0]["fallback_used"] is True

    def test_recorded_entry_carries_a_verified_cost_class(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        manager._providers["ollama"] = _FakeProvider(available=True, response="gerçek cevap")

        manager.route_and_generate("prompt", task_type="short_chat")

        recent = manager.execution_history.recent()
        assert recent[0]["provider"] == "ollama"
        assert recent[0]["cost_class"] == "free"

    def test_unknown_provider_records_unknown_cost_class_not_a_fabricated_one(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        manager._providers = {"mystery_provider": _FakeProvider(available=True, response="ok")}

        manager.route_and_generate("prompt", task_type="short_chat", preferred_provider="mystery_provider")

        recent = manager.execution_history.recent()
        assert recent[0]["provider"] == "mystery_provider"
        assert recent[0]["cost_class"] == "unknown"

    def test_history_recording_failure_never_breaks_the_real_call(self, tmp_path, monkeypatch):
        # Geçmiş kaydı ARIZALANSA bile (ör. disk hatası), gerçek çağrının
        # sonucu asla ETKİLENMEMELİ.
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        manager._providers["ollama"] = _FakeProvider(available=True, response="ok")

        def _broken_record(**kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(manager.execution_history, "record", _broken_record)

        result = manager.route_and_generate("prompt", task_type="short_chat")
        assert result.output == "ok"
        assert result.success is True


class TestUnavailableProviderNeverSilentlySelected:
    """Sprint 40 bölüm 17 (FAILURE TEST): unavailable bir provider asla
    seçilmemeli; fallback sınırlı olmalı (yalnızca TEK bir otomatik
    fallback -- Ollama); sonsuz/gizli bir ücretli sağlayıcıya geçiş
    OLMAMALI."""

    def test_unavailable_preferred_provider_falls_back_without_silently_choosing_paid(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        manager._providers["ollama"] = _FakeProvider(available=True, response="yerel cevap")
        manager._providers["anthropic"] = _FakeProvider(available=False, response="hiç çağrılmamalı")

        result = manager.route_and_generate(
            "prompt", task_type="short_chat", preferred_provider="anthropic",
        )

        assert result.provider_used == "ollama"
        assert "kullanılamıyor" in result.reason

    def test_all_providers_unavailable_returns_a_clear_failure_not_a_paid_call(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        for name in manager.names():
            manager._providers[name] = _FakeProvider(available=False)

        result = manager.route_and_generate("prompt", task_type="short_chat")

        assert result.success is False
        assert result.output  # boş değil, bir hata metni döner


class TestRegistryFallbackCandidates:
    def test_rate_limit_response_falls_back_and_exposes_attempt_chain(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        manager._providers = {
            "ollama": _FakeProvider(response="API hatası: 429 rate limit"),
            "gemini": _FakeProvider(response="fallback ok"),
        }
        result = manager.route_and_generate("hello", task_type="short_chat")
        assert result.success is True
        assert result.provider_used == "gemini"
        assert result.attempted_providers == ("ollama", "gemini")

    def test_empty_malformed_response_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        manager._providers = {
            "ollama": _FakeProvider(response=""),
            "gemini": _FakeProvider(response="valid response"),
        }
        result = manager.route_and_generate("hello", task_type="short_chat")
        assert result.success is True
        assert result.provider_used == "gemini"
        assert result.attempted_providers == ("ollama", "gemini")

    def test_ollama_timeout_skips_unavailable_groq_and_uses_available_general_provider(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        ollama = _FakeProvider(response="Ollama zaman aşımına uğradı.")
        groq = _FakeProvider(available=False, response="çağrılmamalı")
        gemini = _FakeProvider(response="Sistem çalışıyor.")
        aiml = _FakeProvider(response="yedek")
        codex = _FakeProvider(response="çağrılmamalı")
        claude_code = _FakeProvider(response="çağrılmamalı")
        manager._providers = {
            "ollama": ollama,
            "groq": groq,
            "gemini": gemini,
            "aiml": aiml,
            "codex": codex,
            "claude_code": claude_code,
        }

        result = manager.route_and_generate("Bugünün tarihini belirt.", task_type="simple_question")

        assert result.success is True
        assert result.chosen_provider == "ollama"
        assert result.provider_used == "gemini"
        assert result.fallback_used is True
        assert "ollama -> gemini" in result.reason
        assert ollama.calls == 1
        assert gemini.calls == 1
        assert aiml.calls == 0
        assert groq.calls == 0
        assert codex.calls == 0
        assert claude_code.calls == 0

    def test_first_provider_success_does_not_fallback(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        ollama = _FakeProvider(response="ok")
        gemini = _FakeProvider(response="çağrılmamalı")
        manager._providers = {"ollama": ollama, "gemini": gemini}

        result = manager.route_and_generate("selam", task_type="short_chat")

        assert result.success is True
        assert result.fallback_used is False
        assert ollama.calls == 1
        assert gemini.calls == 0

    def test_coding_keeps_codex_then_claude_code_order(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        codex = _FakeProvider(response="codex sağlayıcı hatası: kota")
        claude_code = _FakeProvider(response="düzeltme hazır")
        gemini = _FakeProvider(response="genel yedek")
        manager._providers = {
            "gemini": gemini,
            "claude_code": claude_code,
            "codex": codex,
        }

        result = manager.route_and_generate("bug düzelt", task_type="coding")

        assert result.chosen_provider == "codex"
        assert result.provider_used == "claude_code"
        assert result.fallback_used is True
        assert "codex -> claude_code" in result.reason
        assert codex.calls == 1
        assert claude_code.calls == 1
        assert gemini.calls == 0
