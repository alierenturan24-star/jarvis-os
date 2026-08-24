from __future__ import annotations

from src.finance.manager import FinanceManager
from src.finance.collector import FinanceCollector
from src.providers.provider_manager import ProviderManager, RouteResult


def _route_result(output: str, *, provider: str = "ollama", fallback_used: bool = False, success: bool = True) -> RouteResult:
    return RouteResult(
        output=output, chosen_provider=provider, provider_used=provider, reason="test",
        fallback_used=fallback_used, duration_seconds=0.1, success=success,
    )


def _fake_results() -> list[dict]:
    return [{"title": "Bitcoin haberi", "url": "https://example.com", "summary": "Bitcoin düştü."}]


class TestFinanceManagerAnalyze:
    """Sprint 40: FinanceManager, Research'ün (Summarizer) zaten kullandığı
    ``route_and_generate``'e geçti -- düz ``ModelRouter.generate()`` yerine."""

    def test_successful_analysis_uses_route_and_generate(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(FinanceCollector, "collect", lambda self, asset: _fake_results())
        captured_task_types = []
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: captured_task_types.append(task_type) or _route_result(
                "**JARVIS Değerlendirmesi**\nBitcoin düştü çünkü..."
            ),
        )

        manager = FinanceManager()
        result = manager.analyze("bitcoin")

        assert "Bitcoin düştü çünkü" in result
        assert captured_task_types == ["finance"]

    def test_fallback_used_is_surfaced_in_output(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(FinanceCollector, "collect", lambda self, asset: _fake_results())
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: _route_result(
                "**JARVIS Değerlendirmesi**\nBitcoin analizi.", fallback_used=True,
            ),
        )

        manager = FinanceManager()
        result = manager.analyze("bitcoin")

        assert "otomatik olarak" in result

    def test_llm_failure_falls_back_to_source_summary_not_fabricated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(FinanceCollector, "collect", lambda self, asset: _fake_results())
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: _route_result("Ollama zaman aşımına uğradı.", success=False),
        )

        manager = FinanceManager()
        result = manager.analyze("bitcoin")

        assert "Bitcoin haberi" in result  # source_fallback kaynakları listeler
