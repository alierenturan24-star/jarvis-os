from __future__ import annotations

import time

from src.config.settings import Settings
from src.research.collector import MAX_SEARCH_STEPS, ResearchCollector
from src.research.manager import PROVIDER_FREE_SOURCE_TIMEOUT_SECONDS, ResearchManager
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


def test_provider_free_media_summary_skips_slow_llm_and_persists_sources(monkeypatch, tmp_path):
    sources = [
        {
            "title": "Swiss rail timetable changes announced",
            "url": "https://www.srf.ch/news/schweiz/rail-change",
            "summary": "The timetable change affects several Swiss regions.",
            "published_at": "2026-10-08T10:00:00+00:00",
            "source_language": "de",
            "rejected": False,
        },
        {
            "title": "Les nouveaux horaires ferroviaires en Suisse",
            "url": "https://www.rts.ch/info/suisse/rail-change",
            "summary": "Les changements concernent plusieurs régions.",
            "published_at": "2026-10-08T11:00:00+00:00",
            "source_language": "fr",
            "rejected": False,
        },
    ]

    monkeypatch.setattr(ResearchCollector, "collect", lambda *args, **kwargs: sources)

    def must_not_call_provider(*args, **kwargs):
        raise AssertionError("media source handoff must not wait for an LLM provider")

    monkeypatch.setattr(Summarizer, "summarize", must_not_call_provider)
    monkeypatch.chdir(tmp_path)

    manager = ResearchManager()
    result = manager.research(
        "İsviçre son 7 gün güncel haber",
        force_refresh=True,
        provider_free_summary=True,
    )
    record = manager.knowledge.find_research("İsviçre son 7 gün güncel haber")

    assert "Araştırma tamamlandı" in result
    assert "SEÇİLEN KONU: Swiss rail timetable changes announced" in result
    assert record is not None
    assert len(record["sources"]) == 2
    assert record["sources"][0]["url"].startswith("https://www.srf.ch/")


def test_provider_free_media_collection_has_short_bounded_pass(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_collect(self, topic, max_results_per_source=3, deadline=None, source_preferences=None):
        captured["remaining"] = deadline - time.monotonic()
        return [{
            "title": "Current Swiss report", "url": "https://www.srf.ch/news/current",
            "summary": "Current report", "published_at": "2026-10-08T10:00:00+00:00",
            "rejected": False,
        }]

    monkeypatch.setattr(ResearchCollector, "collect", fake_collect)
    monkeypatch.chdir(tmp_path)

    ResearchManager().research(
        "İsviçre son 7 gün güncel haber",
        force_refresh=True,
        provider_free_summary=True,
    )

    assert 0 < captured["remaining"] <= PROVIDER_FREE_SOURCE_TIMEOUT_SECONDS + 0.1


def test_collector_returns_partial_sources_when_deadline_expires(monkeypatch):
    collector = ResearchCollector()
    calls = {"count": 0}

    def slow_news(**kwargs):
        calls["count"] += 1
        time.sleep(0.08)
        return {"success": True, "results": [{
            "title": "Swiss current event",
            "url": "https://www.srf.ch/news/schweiz/current-event",
            "summary": "A current Swiss event.",
            "published_at": "2026-10-08T10:00:00+00:00",
        }]}

    monkeypatch.setattr(collector.web, "search_news", slow_news)

    rows = collector.collect(
        "İsviçre son 7 gün güncel haber",
        deadline=time.monotonic() + 0.05,
    )

    assert calls["count"] == 1
    assert len(rows) == 1
    assert rows[0]["url"].startswith("https://www.srf.ch/")
