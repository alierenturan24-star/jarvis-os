from types import SimpleNamespace

from src.research.summarizer import Summarizer
from src.utils.llm_utils import is_llm_failure


def _sources():
    return [
        {
            "title": "Swiss rail timetable changes announced",
            "url": "https://www.srf.ch/news/schweiz/rail-change",
            "summary": "The timetable change affects several Swiss regions.",
            "published_at": "2026-09-27T10:00:00+00:00",
            "source_language": "de",
            "publisher": "SRF",
            "reference_role": "factual",
        },
        {
            "title": "Les nouveaux horaires ferroviaires en Suisse",
            "url": "https://www.rts.ch/info/suisse/rail-change",
            "summary": "Les changements concernent plusieurs régions.",
            "published_at": "2026-09-27T11:00:00+00:00",
            "source_language": "fr",
            "publisher": "RTS",
            "reference_role": "factual",
        },
    ]


def test_generic_provider_greeting_is_a_failure_marker():
    assert is_llm_failure("What would you like me to work on?") is True


def test_summarizer_builds_provider_free_structured_report_for_generic_greeting():
    summarizer = Summarizer()
    summarizer.router.manager.route_and_generate = lambda **kwargs: SimpleNamespace(
        output="What would you like me to work on?"
    )

    result = summarizer.summarize("İsviçre son 7 gün güncel haber", _sources())

    assert result.startswith("SEÇİLEN KONU: Swiss rail timetable changes announced")
    assert "2026-09-27T10:00:00+00:00" in result
    assert "https://www.srf.ch/news/schweiz/rail-change" in result
    assert "https://www.rts.ch/info/suisse/rail-change" in result
    assert "JARVIS Önerisi" in result


def test_summarizer_rejects_unstructured_but_nonempty_provider_answer():
    summarizer = Summarizer()
    summarizer.router.manager.route_and_generate = lambda **kwargs: SimpleNamespace(
        output="Here are a few ideas you could explore."
    )

    result = summarizer.summarize("İsviçre son 7 gün güncel haber", _sources())

    assert result.startswith("SEÇİLEN KONU:")
    assert "Here are a few ideas" not in result


def test_provider_free_fallback_skips_previously_attempted_topic():
    summarizer = Summarizer()
    summarizer.router.manager.route_and_generate = lambda **kwargs: SimpleNamespace(
        output="What would you like me to work on?"
    )

    result = summarizer.summarize(
        "İsviçre son 30 gün güncel haber", _sources(),
        exclude_topics=["Swiss rail timetable changes announced"],
    )

    assert result.startswith("SEÇİLEN KONU: Les nouveaux horaires ferroviaires en Suisse")
