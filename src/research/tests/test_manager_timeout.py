from __future__ import annotations

import time

from src.config.settings import Settings
from src.research.collector import MAX_SEARCH_STEPS, ResearchCollector
from src.research.manager import ResearchManager
from src.research.summarizer import Summarizer

# Sprint: research/production pipeline audit -- ResearchCollector.collect()'s
# ``deadline`` parameter already existed but ResearchManager.research() never
# passed one, so a slow early search could silently eat into the budget the
# outer department timeout assumed was left for the summarization call after
# it. These prove the wiring, not the collector's own deadline-enforcement
# logic (already covered structurally by RESEARCH_DEPARTMENT_TASK_TIMEOUT_
# SECONDS's construction in test_research_department_timeout.py).


def test_research_passes_a_bounded_deadline_to_collect(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_collect(self, topic, max_results_per_source=3, deadline=None, source_preferences=None):
        captured["deadline"] = deadline
        captured["called_at"] = time.monotonic()
        return [{"url": "https://example.com/x", "title": "t", "summary": "s",
                 "source_type": "GENERAL_WEB", "rejected": False, "source_preference_match": True}]

    monkeypatch.setattr(ResearchCollector, "collect", fake_collect)
    monkeypatch.setattr(Summarizer, "summarize", lambda self, topic, results, preferred_provider=None: "gerçek özet")
    monkeypatch.chdir(tmp_path)

    ResearchManager().research("bounded deadline test topic")

    assert captured["deadline"] is not None
    remaining = captured["deadline"] - captured["called_at"]
    # Bounded to the real per-search budget * step count -- not unbounded,
    # not the old always-None (unbounded) behavior.
    assert 0 < remaining <= Settings.RESEARCH_PROVIDER_TIMEOUT_SECONDS * MAX_SEARCH_STEPS + 1


def test_research_cycle_timeout_is_reported_honestly(monkeypatch, tmp_path):
    def raise_timeout(self, topic, max_results_per_source=3, deadline=None, source_preferences=None):
        raise TimeoutError("RESEARCH_CYCLE_MAX_RUNTIME_EXCEEDED")

    monkeypatch.setattr(ResearchCollector, "collect", raise_timeout)
    monkeypatch.chdir(tmp_path)

    result = ResearchManager().research("timeout test topic")

    assert "süresi doldu" in result or "RESEARCH_CYCLE_MAX_RUNTIME_EXCEEDED" in result
