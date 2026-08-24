from __future__ import annotations

from src.research_loop.sufficiency import has_repeated_evidence, is_sufficient, refine_goal
from src.strategy.execution_planner import SelfCheckReport


def _check(success_rate=100.0, needs_reresearch=(), missing_info=()) -> SelfCheckReport:
    return SelfCheckReport(
        success_rate=success_rate,
        missing_info=tuple(missing_info),
        needs_reresearch=tuple(needs_reresearch),
        was_cached_research=False,
        cache_note="test",
        review=None,
    )


class TestIsSufficient:
    def test_none_self_check_is_not_sufficient(self):
        sufficient, reason = is_sufficient(None)
        assert sufficient is False
        assert "veri yok" in reason

    def test_needs_reresearch_is_not_sufficient(self):
        sufficient, reason = is_sufficient(_check(needs_reresearch=["x/y: Sandbox FAIL"]))
        assert sufficient is False
        assert "x/y" in reason

    def test_low_success_rate_is_not_sufficient(self):
        sufficient, reason = is_sufficient(_check(success_rate=30.0))
        assert sufficient is False
        assert "%30" in reason

    def test_empty_needs_reresearch_and_high_success_rate_is_sufficient(self):
        sufficient, reason = is_sufficient(_check(success_rate=100.0))
        assert sufficient is True
        assert "yeterli kabul edildi" in reason

    def test_exact_threshold_is_sufficient(self):
        sufficient, _ = is_sufficient(_check(success_rate=60.0), min_success_rate=60.0)
        assert sufficient is True


class TestRefineGoal:
    def test_none_self_check_appends_generic_note(self):
        refined = refine_goal("hedef", None, 2)
        assert refined.startswith("hedef")
        assert "2. tur" in refined

    def test_no_hints_returns_original_goal_unchanged(self):
        refined = refine_goal("hedef", _check(), 2)
        assert refined == "hedef"

    def test_hints_are_appended_from_needs_reresearch(self):
        refined = refine_goal("hedef", _check(needs_reresearch=["repo x: Sandbox FAIL"]), 2)
        assert "hedef" in refined
        assert "repo x" in refined

    def test_hints_are_appended_from_missing_info(self):
        refined = refine_goal("hedef", _check(missing_info=["media: bağlı değil"]), 2)
        assert "media" in refined


class TestHasRepeatedEvidence:
    def test_empty_urls_are_not_repeated(self):
        assert has_repeated_evidence((), ()) is False
        assert has_repeated_evidence(("a",), ()) is False

    def test_fully_disjoint_urls_are_not_repeated(self):
        assert has_repeated_evidence(("a", "b"), ("c", "d")) is False

    def test_fully_overlapping_urls_are_repeated(self):
        assert has_repeated_evidence(("a", "b", "c"), ("a", "b", "c")) is True

    def test_below_threshold_overlap_is_not_repeated(self):
        # 1/3 örtüşme -- eşik (0.9) altında.
        assert has_repeated_evidence(("a",), ("a", "b", "c")) is False

    def test_above_threshold_overlap_is_repeated(self):
        previous = ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j")
        current = ("a", "b", "c", "d", "e", "f", "g", "h", "i", "z")  # 9/10 örtüşme
        assert has_repeated_evidence(previous, current) is True
