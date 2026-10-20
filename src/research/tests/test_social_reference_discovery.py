from __future__ import annotations

from datetime import datetime, timezone

from src.research.collector import ResearchCollector, _wants_short_form_references
from src.research.opportunity import build_selected_opportunity
from src.tools.web_search_tool import WebSearchTool
from src.utils.llm_utils import source_fallback


def test_turkish_short_video_wording_triggers_social_reference_discovery():
    assert _wants_short_form_references(
        "Public Domain görüntülerle 9:16 Türkçe kısa video hazırla"
    ) is True
    assert _wants_short_form_references(
        "TikTok ve Reels'teki başarılı formatları analiz et"
    ) is True


def test_collector_marks_social_video_results_as_format_only(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()

    class _Web:
        def search_news(self, query, max_results=3, timeout_seconds=15.0, timelimit="w"):
            return {
                "success": True,
                "results": [
                    {
                        "title": "Swiss rail update",
                        "url": "https://www.srf.ch/news/schweiz/rail-update",
                        "summary": "Swiss rail operator announces a current change.",
                        "published_at": now,
                        "publisher": "SRF",
                    },
                    {
                        "title": "Swiss rail update confirmed",
                        "url": "https://www.rts.ch/info/suisse/rail-update",
                        "summary": "The same Swiss rail change is confirmed.",
                        "published_at": now,
                        "publisher": "RTS",
                    },
                ],
            }

        def search_videos(self, query, max_results=3, timeout_seconds=15.0):
            return {
                "success": True,
                "results": [
                    {
                        "title": "Fast Swiss rail explainer",
                        "url": "https://www.youtube.com/shorts/example",
                        "summary": "Short hook-first explainer",
                        "publisher": "Creator A",
                        "provider": "YouTube",
                        "platform": "YouTube",
                        "duration": "00:00:31",
                        "statistics": {"views": 120000},
                    },
                    {
                        "title": "Swiss rail quick take",
                        "url": "https://www.tiktok.com/@creator/video/123",
                        "summary": "Quick vertical explainer",
                        "publisher": "Creator B",
                        "provider": "TikTok",
                        "platform": "TikTok",
                        "duration": "00:00:24",
                        "statistics": {"views": 90000},
                    },
                ],
            }

        def search(self, query, max_results=3, timeout_seconds=15.0):
            return {"success": False, "results": []}

    collector = ResearchCollector()
    collector.web = _Web()
    rows = collector.collect(
        "İsviçre için güncel konu bul ve 9:16 Türkçe kısa video hazırla",
        max_results_per_source=3,
    )

    refs = [row for row in rows if row.get("reference_role") == "format_only"]
    facts = [row for row in rows if row.get("reference_role") != "format_only"]
    assert {row["platform"] for row in refs} == {"YouTube", "TikTok"}
    assert len(facts) >= 2


def test_social_references_survive_structured_handoff_but_never_count_as_fact_sources():
    now = datetime.now(timezone.utc).isoformat()
    opportunity = build_selected_opportunity(
        topic="İsviçre için son 7 gün güncel kısa video",
        location_or_market="İsviçre",
        summary="SEÇİLEN KONU: Swiss rail update\nİsviçre güncel ulaşım haberi",
        sources=[
            {
                "title": "Swiss rail update",
                "summary": "Swiss rail operator confirms the current update.",
                "url": "https://www.srf.ch/news/schweiz/rail-update",
                "published_at": now,
            },
            {
                "title": "Swiss rail update confirmed",
                "summary": "Swiss rail operator confirms the current update.",
                "url": "https://www.rts.ch/info/suisse/rail-update",
                "published_at": now,
            },
            {
                "title": "Viral rail short",
                "summary": "Hook-first vertical explainer",
                "url": "https://www.tiktok.com/@creator/video/123",
                "reference_role": "format_only",
                "platform": "TikTok",
                "provider": "TikTok",
                "publisher": "Creator",
                "duration": "00:00:22",
                "statistics": {"views": 250000},
            },
        ],
    )

    assert opportunity.sufficient is True
    assert len(opportunity.supporting_evidence) == 2
    assert len(opportunity.format_references) == 1
    assert opportunity.format_references[0]["platform"] == "TikTok"
    assert opportunity.format_references[0]["summary"] == "Hook-first vertical explainer"


def test_search_videos_supplements_multiple_short_form_platforms(monkeypatch):
    class _DDGS:
        def __init__(self, timeout=None):
            self.timeout = timeout

        def videos(self, *args, **kwargs):
            return [{
                "title": "YT short",
                "content": "https://www.youtube.com/shorts/abc",
                "description": "short",
                "provider": "YouTube",
            }]

        def text(self, query, **kwargs):
            if "site:tiktok.com" in query:
                return [{
                    "title": "TikTok ref",
                    "href": "https://www.tiktok.com/@x/video/456",
                    "body": "vertical clip",
                }]
            if "site:instagram.com/reel" in query:
                return [{
                    "title": "Reel ref",
                    "href": "https://www.instagram.com/reel/xyz/",
                    "body": "reel clip",
                }]
            return []

    monkeypatch.setattr("src.tools.web_search_tool.DDGS", _DDGS)
    result = WebSearchTool().search_videos("Swiss rail", max_results=3)

    assert result["success"] is True
    platforms = {row["platform"] for row in result["results"]}
    assert {"YouTube", "TikTok", "Instagram Reels"} <= platforms


def test_generic_web_social_video_result_is_demoted_to_format_only():
    now = datetime.now(timezone.utc).isoformat()

    class _Web:
        def search_news(self, query, max_results=3, timeout_seconds=15.0, timelimit="w"):
            return {
                "success": True,
                "results": [{
                    "title": "Current Swiss story",
                    "url": "https://www.srf.ch/news/schweiz/current-story",
                    "summary": "Current Swiss factual story.",
                    "published_at": now,
                    "publisher": "SRF",
                }],
            }

        def search_videos(self, query, max_results=3, timeout_seconds=15.0):
            return {"success": False, "results": []}

        def search(self, query, max_results=3, timeout_seconds=15.0):
            return {
                "success": True,
                "results": [{
                    "title": "Old viral short",
                    "url": "https://www.youtube.com/shorts/old-format",
                    "summary": "Jan 2, 2026 · viral short reference",
                }],
            }

    collector = ResearchCollector()
    collector.web = _Web()
    rows = collector.collect(
        "İsviçre için son 7 gün güncel konu bul ve 9:16 kısa video hazırla",
        max_results_per_source=3,
    )

    social = next(row for row in rows if "youtube.com/shorts/" in row["url"])
    assert social["reference_role"] == "format_only"
    facts = [row for row in rows if row["reference_role"] != "format_only"]
    assert all("youtube.com/shorts/" not in row["url"] for row in facts)


def test_source_fallback_never_selects_format_only_social_video_as_news():
    result = source_fallback(
        "İsviçre için son 7 gün güncel haber",
        [{
            "title": "Viral Swiss Short",
            "url": "https://www.youtube.com/shorts/example",
            "summary": "viral format reference",
            "reference_role": "format_only",
            "published_at": "2026-10-20T10:00:00+00:00",
        }],
    )

    assert "SEÇİLEN KONU:" not in result
    assert "format/trend referansları" in result
