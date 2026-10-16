from __future__ import annotations

from datetime import datetime, timezone

from src.research.collector import ResearchCollector
from src.research.opportunity import build_selected_opportunity
from src.utils.llm_utils import source_fallback


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_unrelated_current_swiss_headlines_are_not_same_story():
    now = _now()
    opportunity = build_selected_opportunity(
        topic="İsviçre için son 30 gün içinde aynı haberi doğrulayan en az iki bağımsız kaynakla güncel gündem",
        location_or_market="İsviçre",
        summary="SEÇİLEN KONU: Sesso sicuro: la Confederazione parla ai giovani\nHedef pazar: İsviçre",
        sources=[
            {
                "title": "Sesso sicuro: la Confederazione parla ai giovani",
                "summary": "Campagna LOVE LIFE 2025 per giovani tra 16 e 26 anni, obiettivo 2030.",
                "url": "https://www.rsi.ch/info/svizzera/story-a.html",
                "published_at": now,
                "source_language": "it",
            },
            {
                "title": "Tra pochi anni non ci saranno più ghiacciai in Ticino",
                "summary": "Gli esperti misurano i ghiacciai dell'Adula e del Grauhorn.",
                "url": "https://www.swissinfo.ch/ita/story-b/123",
                "published_at": now,
                "source_language": "it",
            },
        ],
    )

    assert opportunity.sufficient is False
    assert "aynı haber" in opportunity.reason
    assert len(opportunity.supporting_evidence) == 1


def test_multilingual_same_story_can_match_stable_campaign_names_and_numbers():
    now = _now()
    opportunity = build_selected_opportunity(
        topic="İsviçre için son 30 gün içinde aynı haberi doğrulayan en az iki bağımsız kaynakla güncel gündem",
        location_or_market="İsviçre",
        summary="SEÇİLEN KONU: Sesso sicuro: la Confederazione parla ai giovani\nHedef pazar: İsviçre",
        sources=[
            {
                "title": "Sesso sicuro: la Confederazione parla ai giovani",
                "summary": "Campagna LOVE LIFE 2025 per giovani tra 16 e 26 anni, obiettivo 2030.",
                "url": "https://www.rsi.ch/info/svizzera/story-a.html",
                "published_at": now,
                "source_language": "it",
            },
            {
                "title": "Bund richtet LOVE LIFE stärker an junge Menschen",
                "summary": "Die LOVE LIFE Kampagne richtet sich an 16 bis 26-Jährige und nennt Ziele bis 2030.",
                "url": "https://www.srf.ch/news/schweiz/story-a-de",
                "published_at": now,
                "source_language": "de",
            },
        ],
    )

    assert opportunity.sufficient is True
    assert len(opportunity.supporting_evidence) == 2


def test_corroboration_uses_exact_news_search_and_month_window():
    class _Web:
        def __init__(self):
            self.calls = []

        def search_news(self, query, max_results=3, timeout_seconds=15.0, timelimit="w"):
            self.calls.append(("news", query, timelimit))
            return {"success": False, "results": []}

        def search(self, query, max_results=3, timeout_seconds=15.0):
            self.calls.append(("web", query, None))
            return {"success": False, "results": []}

    web = _Web()
    collector = ResearchCollector()
    collector.web = web

    collector.collect(
        '"Sesso sicuro: la Confederazione parla ai giovani" güncel son 30 gün '
        "aynı olayı doğrulayan bağımsız haber kaynakları yayın tarihi İsviçre"
    )

    news_calls = [row for row in web.calls if row[0] == "news"]
    assert news_calls
    assert "Sesso sicuro: la Confederazione parla ai giovani" in news_calls[0][1]
    assert news_calls[0][2] == "m"


def test_provider_free_fallback_skips_recent_topic_when_unseen_candidate_exists():
    now = _now()
    summary = source_fallback(
        "İsviçre güncel gündem",
        [
            {
                "title": "Sesso sicuro: la Confederazione parla ai giovani",
                "published_at": now,
                "url": "https://www.rsi.ch/info/a",
                "summary": "LOVE LIFE kampanyası",
            },
            {
                "title": "Yeni gece treni hattı duyuruldu",
                "published_at": now,
                "url": "https://www.srf.ch/news/b",
                "summary": "Yeni demiryolu bağlantısı",
            },
        ],
        exclude_topics=["Sesso sicuro: la Confederazione parla ai giovani"],
    )
    assert "SEÇİLEN KONU: Yeni gece treni hattı duyuruldu" in summary


def test_provider_free_fallback_does_not_reselect_when_every_candidate_is_excluded():
    now = _now()
    summary = source_fallback(
        "İsviçre güncel gündem",
        [{
            "title": "Sesso sicuro: la Confederazione parla ai giovani",
            "published_at": now,
            "url": "https://www.rsi.ch/info/a",
            "summary": "LOVE LIFE kampanyası",
        }],
        exclude_topics=["Sesso sicuro: la Confederazione parla ai giovani"],
    )
    assert summary.startswith("Model cevap üretmedi:")
