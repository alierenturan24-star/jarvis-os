from __future__ import annotations

from src.providers.provider_manager import ProviderManager, RouteResult
from src.research.local_code_manager import LocalCodeManager


def _route_result(output: str, *, provider: str = "ollama", fallback_used: bool = False, success: bool = True) -> RouteResult:
    return RouteResult(
        output=output, chosen_provider=provider, provider_used=provider, reason="test",
        fallback_used=fallback_used, duration_seconds=0.1, success=success,
    )


class TestLocalCodeManagerAnalyze:
    def test_empty_query_returns_early_without_calling_llm(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: calls.append(prompt) or _route_result("x"),
        )
        manager = LocalCodeManager()
        result = manager.analyze("   ")
        assert "belirtilmedi" in result
        assert calls == []

    def test_no_known_symbol_returns_honest_no_evidence_message_without_calling_llm(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: calls.append(prompt) or _route_result("x"),
        )
        manager = LocalCodeManager()
        result = manager.analyze("Bugün hava çok güzel.")
        assert "bulunamadı" in result
        assert calls == []  # sembol yoksa LLM'e HİÇ gidilmez -- tool-first

    def test_known_symbol_triggers_one_narrow_llm_call_with_local_evidence(self, monkeypatch):
        captured_prompts = []
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: captured_prompts.append((prompt, task_type)) or _route_result(
                "CostOptimizer, ProviderManager örneğini kullanır."
            ),
        )
        manager = LocalCodeManager()
        result = manager.analyze("CostOptimizer nerede kullanılıyor?")

        assert len(captured_prompts) == 1
        prompt, task_type = captured_prompts[0]
        # Sprint 42: "local_code_analysis" ad-hoc etiketi yerine
        # CostOptimizer'ın kanonik "coding" sınıfı kullanılıyor.
        assert task_type == "coding"
        assert "internet KULLANILMADI" in result
        assert "class CostOptimizer" in prompt  # gerçek kod kanıtı prompt'a girdi

    def test_llm_failure_still_returns_the_gathered_evidence(self, monkeypatch):
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: _route_result("Ollama zaman aşımına uğradı.", success=False),
        )
        manager = LocalCodeManager()
        result = manager.analyze("CostOptimizer nedir?")
        assert "sentez üretilemedi" in result
        assert "CostOptimizer" in result  # kanıt yine de gösterilir

    def test_fallback_used_is_surfaced(self, monkeypatch):
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: _route_result("analiz metni", fallback_used=True),
        )
        manager = LocalCodeManager()
        result = manager.analyze("CostOptimizer nedir?")
        assert "otomatik olarak" in result


class _AlwaysAvailableFakeProvider:
    def is_available(self) -> bool:
        return True


def _capture_preferred_provider(captured: dict):
    def _fake_route_and_generate(self, prompt, task_type, **kw):
        captured["preferred"] = kw.get("preferred_provider")
        return _route_result("ok")
    return _fake_route_and_generate


class TestClaudeCodeStrategyConnection:
    """Sprint 44 (CLAUDE CODE WORKER BRIDGE bölüm 7/10): Claude Code
    YALNIZCA gerçekten karmaşık coding/debugging sinyali taşıyan sorularda
    ADAY olmalı -- basit sorularda ASLA seçilmemeli."""

    def test_i_simple_query_never_selects_claude_code(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(ProviderManager, "route_and_generate", _capture_preferred_provider(captured))
        monkeypatch.setattr(
            ProviderManager, "get",
            lambda self, name: _AlwaysAvailableFakeProvider() if name == "claude_code" else None,
        )
        manager = LocalCodeManager()
        manager.analyze("CostOptimizer nedir, kısaca açıkla?")

        assert captured["preferred"] != "claude_code"

    def test_j_complex_debugging_query_selects_claude_code_when_available(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(ProviderManager, "route_and_generate", _capture_preferred_provider(captured))
        monkeypatch.setattr(
            ProviderManager, "get",
            lambda self, name: _AlwaysAvailableFakeProvider() if name == "claude_code" else None,
        )
        manager = LocalCodeManager()
        manager.analyze("CostOptimizer'da bir hata var, neden çalışmıyor? Debug et.")

        assert captured["preferred"] == "claude_code"

    def test_complex_query_falls_back_to_ollama_when_claude_code_unavailable(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(ProviderManager, "route_and_generate", _capture_preferred_provider(captured))
        monkeypatch.setattr(ProviderManager, "get", lambda self, name: None)
        manager = LocalCodeManager()
        manager.analyze("CostOptimizer'da bir hata var, neden çalışmıyor? Debug et.")

        assert captured["preferred"] == "ollama"
