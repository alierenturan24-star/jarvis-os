from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from src.knowledge.knowledge_base import KnowledgeBase
from src.media.manager import MediaManager, _unsupported_research_claims
from src.media.quality import _check_narrative_relevance
from src.media.renderer import find_edge_tts
from src.research.collector import ResearchCollector
from src.research.opportunity import build_selected_opportunity
from src.mission.department_orchestrator import _media_research_query
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


def test_selected_opportunity_hands_only_clean_selected_headline_to_media():
    summary = (
        "SEÇİLEN KONU: 25 Jahre nach dem Grounding: Die Swiss fliegt in deutlich weniger Länder\n"
        "AI sağlayıcısı uygun araştırma özeti döndürmediği için sağlayıcısız rapor oluşturuldu.\n"
        "Araştırma isteği ve pazarı: İsviçre için son 30 gün."
    )
    opportunity = build_selected_opportunity(
        topic="İsviçre son 30 gün güncel haber",
        location_or_market="İsviçre",
        summary=summary,
        sources=_current_sources(),
    )
    assert opportunity.sufficient is True
    assert opportunity.selected_topic == (
        "25 Jahre nach dem Grounding: Die Swiss fliegt in deutlich weniger Länder"
    )
    assert "AI sağlayıcısı" not in opportunity.selected_topic


def test_two_source_requirement_survives_media_query_rewrite():
    query = _media_research_query(
        "İsviçre için haber bul; iki güvenilir kaynak yoksa 30 güne genişlet. Video hazırla."
    )
    assert "en az iki bağımsız kaynak" in query


def test_explicit_two_source_rule_rejects_unrelated_current_headlines():
    published = datetime.now(timezone.utc).isoformat()
    opportunity = build_selected_opportunity(
        topic="İsviçre son 30 gün aynı haberi doğrulayan en az iki bağımsız kaynakla",
        location_or_market="İsviçre",
        summary="SEÇİLEN KONU: Malaysia schickt Rohingya zurück nach Myanmar und bricht ein Tabu\nİsviçre gündemi",
        sources=[
            {"title": "Malaysia schickt Rohingya zurück nach Myanmar", "summary": "Rohingya werden zurückgeschickt.",
             "url": "https://www.nzz.ch/a", "published_at": published},
            {"title": "Trump lädt Putin zum G20 ein", "summary": "Europäer reagieren.",
             "url": "https://www.srf.ch/b", "published_at": published},
        ],
    )
    assert opportunity.sufficient is False
    assert len(opportunity.supporting_evidence) == 1
    assert "aynı haber" in opportunity.reason


def test_recent_topic_is_rejected_even_when_punctuation_changes():
    published = datetime.now(timezone.utc).isoformat()
    headline = "Malaysia schickt Rohingya zurück nach Myanmar – und bricht damit ein Tabu"
    opportunity = build_selected_opportunity(
        topic="İsviçre son 30 gün güncel haber",
        location_or_market="İsviçre",
        summary=f"SEÇİLEN KONU: {headline}\nİsviçre gündemi",
        sources=[
            {"title": headline, "url": "https://www.nzz.ch/a", "published_at": published},
            {"title": headline, "url": "https://www.srf.ch/b", "published_at": published},
        ],
        exclude_topics=["Malaysia schickt Rohingya zurück nach Myanmar und bricht damit ein Tabu"],
    )
    assert opportunity.sufficient is False
    assert "zaten" in opportunity.reason


def test_relative_search_timestamp_counts_as_current_evidence():
    now = datetime.now(timezone.utc).isoformat()
    headline = "Swiss rail night train expansion"
    opportunity = build_selected_opportunity(
        topic="İsviçre son 7 gün güncel haber",
        location_or_market="İsviçre",
        summary=f"SEÇİLEN KONU: {headline}\nİsviçre gündemi",
        sources=[
            {"title": headline, "url": "https://www.srf.ch/a", "published_at": "Opinion18 hours ago"},
            {"title": headline, "url": "https://www.rts.ch/b", "published_at": now},
        ],
    )
    assert opportunity.sufficient is True
    assert len(opportunity.supporting_evidence) == 2


def test_live_failure_replay_accepts_nzz_and_bbc_when_relative_dates_are_in_snippets():
    headline = "Malaysia schickt Rohingya zurück nach Myanmar – und bricht damit ein Tabu"
    opportunity = build_selected_opportunity(
        topic="İsviçre son 30 gün aynı haberi doğrulayan en az iki bağımsız kaynakla",
        location_or_market="İsviçre",
        summary=f"SEÇİLEN KONU: {headline}\nHedef pazar: İsviçre",
        sources=[
            {"title": headline, "summary": "Am Mittwochmorgen fuhren die Reisebusse vor.",
             "url": "https://www.nzz.ch/international/rohingya-a",
             "published_at": datetime.now(timezone.utc).isoformat()},
            {"title": "Malaysia schickt 1500 Rohingya zurück nach Myanmar",
             "summary": "10 hours ago - Das Regime bietet an, Flüchtlinge zurückzunehmen.",
             "url": "https://www.nzz.ch/international/rohingya-b"},
            {"title": "Malaysia begins controversial repatriation of asylum seekers to Myanmar",
             "summary": "8 hours ago - Human rights groups condemned the repatriation.",
             "url": "https://www.bbc.com/news/articles/example"},
        ],
    )
    assert opportunity.sufficient is True
    assert {"www.nzz.ch", "www.bbc.com"} == {
        __import__("urllib.parse", fromlist=["urlparse"]).urlparse(row["url"]).hostname
        for row in opportunity.supporting_evidence
    }


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
        def get(self, name):
            return None

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
        def get(self, name):
            return None

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


def test_live_pope_plan_rejects_claims_missing_from_source_snippets():
    opportunity = {
        "selected_topic": "Knoten in der Lunge: Papst wird operiert",
        "supporting_evidence": [{
            "title": "Papst wird wegen Knoten in der Lunge operiert",
            "summary": "Der Knoten wurde früh entdeckt; eine Operation ist angekündigt.",
        }],
    }
    plan = (
        "İsviçre'den son dakika. Kötü hücre erken bulundu. Sağlık durumu stabil. "
        "Doktorlar operasyonun başarılı geçmesini bekliyor. Erken teşhis hayat kurtardı. "
        "Tüm dünyadan dualar geliyor."
    )

    unsupported = _unsupported_research_claims(plan, opportunity)

    assert set(unsupported) == {
        "kanser/kötü hücre", "sağlık durumunun stabil olduğu",
        "doktorların başarı beklentisi", "hayat kurtardığı",
        "dünya çapında dua/tepki", "olayın İsviçre kaynaklı olduğu",
    }


def test_media_manager_blocks_unsupported_claims_after_failed_correction(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []
    bad_plan = """SENARYO
İsviçre'den son dakika. Papa'nın sağlık durumu stabil ve erken teşhis hayat kurtardı.

SAHNELER
Sahne 1 (~15 sn): Anlatım: Sağlık durumu stabil | Görsel: Papa | Ekran yazısı: Stabil
Sahne 2 (~15 sn): Anlatım: Erken teşhis hayat kurtardı | Görsel: Akciğer | Ekran yazısı: Hayat kurtardı
Sahne 3 (~15 sn): Anlatım: Ameliyat planlandı | Görsel: Hastane | Ekran yazısı: Ameliyat
Sahne 4 (~15 sn): Anlatım: Haber doğrulandı | Görsel: Kaynak | Ekran yazısı: Kaynaklı

SESLENDİRME PLANI
Türkçe anlatım.

GÖRSEL/VİDEO PLANI
Özgün kartlar.

ALTYAZI PLANI
Türkçe altyazı.

THUMBNAIL FİKRİ
Papa portresi.

BAŞLIK
Papa'nın Ameliyatı

AÇIKLAMA
Kaynaklı haber.

ETİKETLER
Papa, sağlık, haber"""

    class _Manager:
        def get(self, name):
            return None

        def route_and_generate(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                output=bad_plan, success=True, fallback_used=False,
                chosen_provider="ollama", provider_used="ollama",
            )

    manager = MediaManager()
    manager.router = SimpleNamespace(manager=_Manager())
    output = manager.plan(
        "Knoten in der Lunge: Papst wird operiert", produce_artifact=True,
        request_text="Public Domain görüntülerle Türkçe video hazırla",
        research_opportunity={
            "selected_topic": "Knoten in der Lunge: Papst wird operiert",
            "location_or_market": "İsviçre", "why_current": "3 kaynak",
            "supporting_evidence": [{
                "title": "Papst wird wegen Knoten operiert",
                "summary": "Der Knoten wurde früh entdeckt; die Operation ist angekündigt.",
                "url": "https://www.srf.ch/news/papst", "published_at": "2026-10-11",
            }], "format_references": [],
        },
        free_only=True,
    )

    assert output.startswith("VIDEO RENDER: BLOCKED_UNSUPPORTED_CLAIMS")
    assert manager.last_artifact_path == ""
    assert len(calls) == 2
    assert all(call["allowed_cost_classes"] == ("free", "plan") for call in calls)
