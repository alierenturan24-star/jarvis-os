from __future__ import annotations

from src.providers.cost_optimizer import CostOptimizer
from src.providers.provider_manager import ProviderManager


class _Provider:
    def __init__(self, available: bool = True, response: str = "ok") -> None:
        self._available = available
        self._response = response
        self.calls = 0

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, model: str | None = None) -> str:
        self.calls += 1
        return self._response


def _manager(tmp_path, monkeypatch, **providers) -> ProviderManager:
    monkeypatch.chdir(tmp_path)
    manager = ProviderManager()
    manager._providers = providers
    return manager


class TestCostClass:
    def test_ollama_and_free_tier_cloud_are_free(self):
        assert CostOptimizer.cost_class("ollama") == "free"
        assert CostOptimizer.cost_class("gemini") == "free"
        assert CostOptimizer.cost_class("groq") == "free"
        assert CostOptimizer.cost_class("openrouter") == "free"

    def test_cli_subscription_workers_are_plan_not_free(self):
        # PLAN_CLI_PROVIDERS is deliberately never labeled "free" -- it is
        # a pre-authenticated subscription, not a verified free API tier.
        assert CostOptimizer.cost_class("codex") == "plan"
        assert CostOptimizer.cost_class("claude_code") == "plan"

    def test_known_paid_providers_are_paid(self):
        assert CostOptimizer.cost_class("openai") == "paid"
        assert CostOptimizer.cost_class("anthropic") == "paid"
        assert CostOptimizer.cost_class("deepseek") == "paid"
        assert CostOptimizer.cost_class("aiml") == "paid"

    def test_unrecognized_provider_is_unknown_not_fabricated(self):
        assert CostOptimizer.cost_class("some_future_provider") == "unknown"

    def test_alias_normalization_applies(self):
        assert CostOptimizer.cost_class("local") == "free"  # alias for ollama
        assert CostOptimizer.cost_class("google") == "free"  # alias for gemini


class TestDecideStaysDeterministicRegardlessOfHistory:
    """execution_history.py states the rule explicitly: no recorded
    execution entry may automatically change a routing decision -- history
    is for future human/reporting reads only (``success_rate``), never a
    silent input to ``decide()``. These tests lock that invariant so a
    future "let's use history to pick the better provider" change doesn't
    reintroduce it (it did, once, in this file's history, and broke
    test_codex_routing.py::test_coding_task_prefers_codex against a real,
    machine-local accumulated history file)."""

    def test_coding_prefers_codex_even_with_worse_recorded_history(self, tmp_path, monkeypatch):
        manager = _manager(tmp_path, monkeypatch, codex=_Provider(), claude_code=_Provider())
        for _ in range(10):
            manager.execution_history.record(
                task_type="coding", provider="codex", success=False,
                fallback_used=False, duration_seconds=1.0,
            )
        for _ in range(10):
            manager.execution_history.record(
                task_type="coding", provider="claude_code", success=True,
                fallback_used=False, duration_seconds=1.0,
            )

        decision = CostOptimizer(manager).decide("coding")
        assert decision.provider == "codex"

    def test_research_prefers_gemini_even_with_worse_recorded_history(self, tmp_path, monkeypatch):
        manager = _manager(tmp_path, monkeypatch, gemini=_Provider(), openrouter=_Provider())
        for _ in range(10):
            manager.execution_history.record(
                task_type="research", provider="gemini", success=False,
                fallback_used=False, duration_seconds=1.0,
            )
        for _ in range(10):
            manager.execution_history.record(
                task_type="research", provider="openrouter", success=True,
                fallback_used=False, duration_seconds=1.0,
            )

        decision = CostOptimizer(manager).decide("research")
        assert decision.provider == "gemini"
