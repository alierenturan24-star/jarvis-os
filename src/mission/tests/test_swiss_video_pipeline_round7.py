from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from src.knowledge.knowledge_base import KnowledgeBase
from src.media.manager import MediaManager
from src.media.quality import _check_narrative_relevance
from src.media.renderer import find_edge_tts
from src.research.collector import ResearchCollector
from src.research.opportunity import build_selected_opportunity
from src.research.summarizer import Summarizer
from src.tools.web_search_tool import WebSearchTool


def _current_sources() -> list[dict]:
    published = datetime.now(timezone.utc).isoformat()
    return [
        {
            "title": "Schweizer Energieprojekt", "url": "https://www.srf.ch/news/schweiz/projekt",
            "summary": "İsviçre enerji projesi bugün açıklandı.", "published_at": published,
            "publisher": "SRF", "source_language": "de", "reference_role": "factual",
        },
        {
            "title": "Projet énergétique suisse", "url": "https://www.rts.ch/info/suisse/projet",
            "summary": "İsviçre enerji projesinin ayrıntıları.", "published_at": published,
            "publisher": "RTS", "source_language": "fr", "reference_role": "factual",
        },
        {
            "title": "Progetto energetico svizzero", "url": "https://www.rsi.ch/info/svizzera/progetto",
            "summary": "İsviçre enerji projesinin yerel etkisi.", "published_at": published,
            "publisher": "RSI", "source_language": "it", "reference_role": "factual",
        },
    ]


def test_video_search_returns_metadata_only_format_reference(monkeypatch):
    class _DDGS:
        def __init__(self, **kwargs):
            pass

        def videos(self, *args, **kwargs):
            return [{
                "title": "Swiss explainer Short", "content": "https://youtube.com/shorts/abc123",
                "description": "Fast hook and three-step explainer", "published": "2026-09-23",
                "publisher": "Example Channel", "provider": "YouTube", "duration": "00:42",
                "statistics": {"viewCount": 120000}, "thumbnail": "must-not-be-copied",
            }]

    monkeypatch.setattr("src.tools.web_search_tool.DDGS", _DDGS)
    result = WebSearchTool().search_videos("Swiss current explainer")

    assert result["success"] is True
    row = result["results"][0]
    assert row["url"] == "https://youtube.com/shorts/abc123"
    assert row["duration"] == "00:42"
    assert row["statistics"]["viewCount"] == 120000
    assert "thumbnail" not in row


def test_collector_marks_video_results_format_only():
    class _Web:
        def search_news(self, **kwargs):
            return {"success": False}

        def search(self, **kwargs):
            return {"success": False}

        def search_videos(self, **kwargs):
            return {"success": True, "results": [{
                "title": "Public Short", "url": "https://youtube.com/shorts/xyz",
                "publisher": "Channel", "provider": "YouTube", "duration": "00:31",
                "statistics": {"viewCount": 50},
            }]}

    collector = ResearchCollector()
    collector.web = _Web()
    rows = collector.collect("İsviçre güncel kısa video (Shorts) fırsatı")

    assert len(rows) == 1
    assert rows[0]["reference_role"] == "format_only"
    assert rows[0]["search_channel"] == "VIDEO_FORMAT_DE"


def test_knowledge_roundtrip_preserves_evidence_and_format_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sources = _current_sources() + [{
        "title": "Format example", "url": "https://youtube.com/shorts/format1",
        "publisher": "Channel", "provider": "YouTube", "reference_role": "format_only",
        "duration": "00:38", "statistics": {"viewCount": 9000},
    }]
    knowledge = KnowledgeBase()
    knowledge.remember_research("Swiss topic", "İsviçre güncel enerji projesi", "report.md", 4, sources)

    stored = knowledge.find_research("Swiss topic")
    assert stored is not None
    assert stored["sources"][0]["published_at"]
    assert stored["sources"][0]["source_language"] == "de"
    assert stored["sources"][3]["reference_role"] == "format_only"
    assert stored["sources"][3]["statistics"]["viewCount"] == 9000

    opportunity = build_selected_opportunity(
        topic="İsviçre son 7 gün güncel Almanca Fransızca İtalyanca",
        location_or_market="İsviçre", summary=stored["summary"], sources=stored["sources"],
    )
    assert opportunity.sufficient is True
    assert len(opportunity.supporting_evidence) == 3
    assert len(opportunity.format_references) == 1
    assert opportunity.format_references[0]["url"].endswith("/format1")


def test_summarizer_keeps_format_reference_after_many_news_rows():
    captured = {}

    class _Manager:
        def route_and_generate(self, **kwargs):
            captured["prompt"] = kwargs["prompt"]
            return SimpleNamespace(output="SEÇİLEN KONU: İsviçre enerji projesi")

    news = []
    for index in range(10):
        news.append({
            "title": f"News {index}", "url": f"https://www.srf.ch/news/{index}",
            "summary": "İsviçre haber", "published_at": "2026-09-23", "source_language": "de",
            "publisher": "SRF", "reference_role": "factual",
        })
    news.append({
        "title": "Fast Swiss explainer", "url": "https://youtube.com/shorts/ref1",
        "summary": "question hook", "publisher": "Channel", "reference_role": "format_only",
        "duration": "00:29", "statistics": {"viewCount": 70000},
    })
    summarizer = Summarizer()
    summarizer.router = SimpleNamespace(manager=_Manager())
    summarizer.summarize("İsviçre Shorts", news)

    prompt = captured["prompt"]
    assert "Fast Swiss explainer" in prompt
    assert "Referans rolü: format_only" in prompt
    assert "başlığı, metni, kapağı" in prompt


def test_media_planner_receives_format_reference_with_no_copy_boundary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured = {}

    class _Manager:
        def route_and_generate(self, **kwargs):
            captured["prompt"] = kwargs["prompt"]
            return SimpleNamespace(
                output="SENARYO\nÖzgün metin\n\nSAHNELER\nSahne 1 (~10 sn): Anlatım: Test | Görsel: Test | Ekran yazısı: Test",
                fallback_used=False, chosen_provider="test", provider_used="test",
            )

    manager = MediaManager()
    manager.router = SimpleNamespace(manager=_Manager())
    manager.plan("Özgün İsviçre videosu", research_opportunity={
        "selected_topic": "İsviçre enerji projesi", "location_or_market": "İsviçre",
        "why_current": "3 güncel kaynak", "supporting_evidence": [],
        "format_references": [{
            "title": "Fast explainer", "url": "https://youtube.com/shorts/ref",
            "publisher": "Channel", "duration": "00:35", "statistics": {"viewCount": 10},
        }],
    })

    prompt = captured["prompt"]
    assert "Fast explainer" in prompt
    assert "YALNIZ soyut hook/tempo/hikâye/başlık kalıbı" in prompt
    assert "kopyalanamaz" in prompt


def test_edge_tts_is_found_next_to_unactivated_venv_python(tmp_path, monkeypatch):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    python = scripts / "python.exe"
    edge = scripts / "edge-tts.exe"
    python.write_bytes(b"python")
    edge.write_bytes(b"edge")
    monkeypatch.setattr("src.media.renderer.shutil.which", lambda name: None)
    monkeypatch.setattr("src.media.renderer.sys.executable", str(python))

    assert find_edge_tts() == str(edge.resolve())


def test_cross_language_swiss_goal_relevance_is_not_falsely_rejected():
    result = _check_narrative_relevance(
        "İsviçre güncel enerji projesi özgün bilgilendirici Shorts",
        {
            "script": "Die Schweiz erklärt das neue Energieprojekt.",
            "topic": "Schweizer Energieprojekt", "selected_title": "Energie in der Schweiz",
            "hook": "Was ändert sich?", "ending": "Das ist jetzt wichtig.",
            "story_concept": "Aktuelles Energieprojekt", "scene_descriptions": [],
        },
    )

    assert result["passed"] is True
    assert result["overlap_ratio"] >= 0.15
