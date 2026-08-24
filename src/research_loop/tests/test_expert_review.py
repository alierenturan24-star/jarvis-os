from __future__ import annotations

from src.research_loop.expert_review import decide_and_run_expert_review
from src.research_loop.models import ImprovementCandidate
from src.strategy.models import SelfImprovementReview


class _FakeProvider:
    def __init__(self, available: bool) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available


class _FakeProviderManager:
    """Sprint 37: gerçek ANTHROPIC_API_KEY/ağ bağımlılığı olmadan,
    deterministik bir sahte ``ProviderManager`` -- ZATEN VAR OLAN
    ``src.strategy.tests.test_strategy_engine._FakeProviderManager``
    ile AYNI desen."""

    def __init__(self, anthropic_available: bool, response: str = "Claude cevabı.") -> None:
        self._available = anthropic_available
        self._response = response
        self.last_prompt: str | None = None
        self.last_provider_name: str | None = None

    def get(self, name: str):
        if name != "anthropic":
            return None
        return _FakeProvider(self._available)

    def route_and_generate(self, prompt: str, task_type: str, preferred_provider: str):
        from src.providers.provider_manager import RouteResult
        self.last_prompt = prompt
        self.last_provider_name = preferred_provider
        return RouteResult(self._response, preferred_provider, preferred_provider, "test", False, 0.0, True,
                           (preferred_provider,))


def _candidate(title="A", score=50, cost_advantage=50) -> ImprovementCandidate:
    return ImprovementCandidate(
        goal="hedef", source="ai_discovery", title=title, url=f"https://x.com/{title}",
        finding="bulgu", gain_note="kazanç", risk_note="risk", recommendation="öneri",
        score=score, cost_advantage=cost_advantage, round_number=1,
    )


def _review(quality_risk=False) -> SelfImprovementReview:
    return SelfImprovementReview(
        cheaper_ai_possible=False, cheaper_ai_note="n", faster_ai_possible=False, faster_ai_note="n",
        quality_risk=quality_risk, quality_risk_note="kalite notu", new_free_model_available=False,
        new_free_model_note="n",
    )


class TestDecideAndRunExpertReview:
    def test_no_candidates_skips_review(self):
        manager = _FakeProviderManager(anthropic_available=True)
        text, reason = decide_and_run_expert_review((), None, manager, "hedef")
        assert text is None
        assert "değerlendirilecek bir şey yok" in reason
        assert manager.last_prompt is None

    def test_quality_risk_true_and_provider_available_calls_claude_with_narrow_prompt(self):
        manager = _FakeProviderManager(anthropic_available=True, response="X daha uygun.")
        candidates = (_candidate("A"),)
        text, reason = decide_and_run_expert_review(candidates, _review(quality_risk=True), manager, "hedef")
        assert text == "X daha uygun."
        assert manager.last_provider_name == "anthropic"
        assert "hedef" in manager.last_prompt
        assert "A" in manager.last_prompt
        # Tüm konuşma geçmişi DEĞİL, yalnızca aday özetleri gönderilmeli.
        assert len(manager.last_prompt) < 3000

    def test_quality_risk_true_but_provider_unavailable_reports_honestly(self):
        manager = _FakeProviderManager(anthropic_available=False)
        candidates = (_candidate("A"),)
        text, reason = decide_and_run_expert_review(candidates, _review(quality_risk=True), manager, "hedef")
        assert text is None
        assert "ANTHROPIC_API_KEY" in reason
        assert manager.last_prompt is None

    def test_many_candidates_no_clear_winner_triggers_review(self):
        manager = _FakeProviderManager(anthropic_available=True)
        candidates = (_candidate("A", score=60), _candidate("B", score=58), _candidate("C", score=55))
        text, reason = decide_and_run_expert_review(candidates, _review(quality_risk=False), manager, "hedef")
        assert text is not None
        assert "net bir kazanan yok" in reason

    def test_clear_free_winner_skips_review(self):
        manager = _FakeProviderManager(anthropic_available=True)
        candidates = (_candidate("A", score=95), _candidate("B", score=40), _candidate("C", score=30))
        text, reason = decide_and_run_expert_review(candidates, _review(quality_risk=False), manager, "hedef")
        assert text is None
        assert manager.last_prompt is None
        assert "Claude gerekmedi" in reason

    def test_single_candidate_no_quality_risk_skips_review(self):
        manager = _FakeProviderManager(anthropic_available=True)
        text, reason = decide_and_run_expert_review((_candidate("A"),), _review(quality_risk=False), manager, "hedef")
        assert text is None
        assert manager.last_prompt is None
