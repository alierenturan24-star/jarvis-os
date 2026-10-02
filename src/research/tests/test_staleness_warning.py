from __future__ import annotations

from src.research.collector import ResearchCollector
from src.research.manager import (
    ResearchManager,
    staleness_warning,
    topic_wants_current_information,
)
from src.research.opportunity import build_selected_opportunity
from src.research.summarizer import Summarizer

# Mission repair (real Swiss-Insider-Shorts follow-up evidence, item 5): a
# real "today's opportunity" mission got back a summary titled
# "İsviçre'de 2024'te En Çok Kazandıran Yan İş Fikirleri" while the system
# clock was 2026, with no mechanism flagging the mismatch. These tests use
# a sanitized, generic fixture (not this specific topic) since the fix must
# be generic, not hardcoded to Swiss/2024/2026.


class TestTopicWantsCurrentInformation:
    def test_detects_today_current_now_cues(self):
        assert topic_wants_current_information("Research today's best opportunity") is True
        assert topic_wants_current_information("Bugünün en iyi fırsatını araştır") is True
        assert topic_wants_current_information("What's the current market trend") is True
        assert topic_wants_current_information("Güncel piyasa durumunu araştır") is True

    def test_plain_historical_topic_is_not_flagged(self):
        assert topic_wants_current_information("Research the history of the Swiss watch industry") is False


class TestStalenessWarning:
    def test_stale_year_only_triggers_a_warning(self):
        warning = staleness_warning(
            "Research today's highest-potential opportunity",
            "En çok kazandıran yan iş fikirleri (2024 verilerine göre).",
            current_year=2026,
        )
        assert warning is not None
        assert "2024" in warning
        assert "2026" in warning

    def test_current_year_mention_suppresses_the_warning(self):
        warning = staleness_warning(
            "Research today's highest-potential opportunity",
            "2026'nın en güncel fırsatları (2024 verileriyle karşılaştırmalı).",
            current_year=2026,
        )
        assert warning is None

    def test_non_current_topic_is_never_flagged_even_with_a_stale_year(self):
        warning = staleness_warning(
            "Compare 2024's market performance to prior years",
            "2024 sonuçları şöyleydi...",
            current_year=2026,
        )
        assert warning is None

    def test_no_year_mentioned_is_never_flagged(self):
        warning = staleness_warning(
            "Research today's highest-potential opportunity",
            "En çok kazandıran yan iş fikirleri.",
            current_year=2026,
        )
        assert warning is None


def test_swiss_web_snippet_european_dates_and_multilingual_anchor_are_valid_evidence():
    opportunity = build_selected_opportunity(
        topic=("İsviçre son 7 gün aynı haberi doğrulayan en az iki bağımsız kaynakla "
               "güncel haber"),
        location_or_market="İsviçre",
        summary=("SEÇİLEN KONU: Arrivano i robotaxi anche in Svizzera nel Canton Zurigo\n"
                 "İsviçre robotaxi gündemi"),
        sources=[
            {
                "title": "Arrivano i robotaxi anche in Svizzera nel Canton Zurigo",
                "url": "https://www.cdt.ch/news/robotaxi",
                "summary": "26.09.2026 · Robotaxi nel Canton Zurigo.",
            },
            {
                "title": "Ab jetzt ist das erste Robotaxi der Schweiz im Einsatz",
                "url": "https://www.srf.ch/news/schweiz/robotaxi",
                "summary": "28.09.2026 · Das Robotaxi fährt im Zürcher Furttal.",
            },
        ],
    )

    assert opportunity.sufficient is True
    assert len(opportunity.supporting_evidence) == 2


class TestResearchManagerSurfacesStaleness:
    def test_fresh_research_with_stale_year_gets_a_visible_warning(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            ResearchCollector, "collect",
            lambda self, topic, max_results_per_source=3, deadline=None, source_preferences=None: [
                {"url": "https://example.com/x", "title": "t",
                 "summary": "En çok kazandıran yan iş fikirleri (2024).",
                 "source_type": "GENERAL_WEB", "rejected": False, "source_preference_match": True},
            ],
        )
        monkeypatch.setattr(
            Summarizer, "summarize",
            lambda self, topic, results, preferred_provider=None: "En çok kazandıran yan iş fikirleri (2024).",
        )

        output = ResearchManager().research("today's highest-potential opportunity")

        assert "UYARI (GÜNCELLİK)" in output
        assert "2024" in output

    def test_fresh_research_without_currency_cue_has_no_warning(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            ResearchCollector, "collect",
            lambda self, topic, max_results_per_source=3, deadline=None, source_preferences=None: [
                {"url": "https://example.com/x", "title": "t", "summary": "2024 tarihli genel bir özet.",
                 "source_type": "GENERAL_WEB", "rejected": False, "source_preference_match": True},
            ],
        )
        monkeypatch.setattr(
            Summarizer, "summarize",
            lambda self, topic, results, preferred_provider=None: "2024 tarihli genel bir özet.",
        )

        output = ResearchManager().research("İsviçre çikolata endüstrisinin tarihini araştır")

        assert "UYARI (GÜNCELLİK)" not in output
