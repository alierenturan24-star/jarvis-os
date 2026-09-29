from datetime import datetime, timedelta, timezone

from src.agents.research_agent import ResearchAgent, _WINDOW_FALLBACK_CUES
from src.planner.task import Task
from src.knowledge.knowledge_base import KnowledgeBase


def test_current_media_research_retries_once_with_different_query_shape():
    now = datetime.now(timezone.utc).isoformat()

    class _Knowledge:
        rows = {}

        def find_research(self, topic):
            return self.rows.get(topic)

    class _Manager:
        def __init__(self):
            self.knowledge = _Knowledge()
            self.calls = []

        def research(self, topic, **kwargs):
            self.calls.append(topic)
            if "alternative_source_pass" in topic.casefold():
                self.knowledge.rows[topic] = {
                    "summary": "İsviçre'de güncel enerji tasarrufu kararı kısa video için seçildi.",
                    "created_at": now,
                    "sources": [
                        {"title": "SRF aktuell", "url": "https://www.srf.ch/news/schweiz/a",
                         "published_at": now, "source_language": "de"},
                        {"title": "RTS actuel", "url": "https://www.rts.ch/info/suisse/b",
                         "published_at": now, "source_language": "fr"},
                    ],
                }
                return "ikinci tarama tamamlandı"
            self.knowledge.rows[topic] = {
                "summary": "İsviçre PISA 2025 sonucu",
                "created_at": now,
                "sources": [{"title": "eski", "url": "https://www.srf.ch/news/old",
                             "published_at": "2025-01-01T00:00:00+00:00"}],
            }
            return "ilk tarama tamamlandı"

    agent = ResearchAgent()
    agent.manager = _Manager()
    task = Task(
        action="current research", agent="research",
        target="İsviçre için son 7 gün güncel konu araştır",
        metadata={"market_context": "İsviçre"},
    )

    output = agent.execute(task)

    assert len(agent.manager.calls) == 2
    assert "ALTERNATIVE_SOURCE_PASS" in agent.manager.calls[1]
    assert "OTOMATİK GÜNCEL KAYNAK YENİDEN DENEMESİ" in output
    assert task.metadata["report"]["sufficient"] is True
    assert task.metadata["report"]["freshness_status"] == "CURRENT"


def test_current_media_research_can_widen_to_declared_30_day_fallback():
    now = datetime.now(timezone.utc)
    older = now.replace(day=max(1, now.day - 12)).isoformat()

    class _Knowledge:
        rows = {}

        def find_research(self, topic):
            return self.rows.get(topic)

    class _Manager:
        def __init__(self):
            self.knowledge = _Knowledge()
            self.calls = []

        def research(self, topic, **kwargs):
            self.calls.append(topic)
            if "son 30 gün" in topic:
                self.knowledge.rows[topic] = {
                    "summary": "İsviçre'de doğrulanmış güncel ulaşım gelişmesi seçildi.",
                    "created_at": now.isoformat(),
                    "sources": [
                        {"title": "SRF", "url": "https://www.srf.ch/news/schweiz/a",
                         "published_at": older, "source_language": "de"},
                        {"title": "RTS", "url": "https://www.rts.ch/info/suisse/b",
                         "published_at": older, "source_language": "fr"},
                    ],
                }
                return "30 günlük yedek tarama tamamlandı"
            self.knowledge.rows[topic] = {
                "summary": "İsviçre için güncel konu bulunamadı.",
                "created_at": now.isoformat(), "sources": [],
            }
            return "ilk tarama tamamlandı"

    agent = ResearchAgent()
    agent.manager = _Manager()
    command = (
        "İsviçre için son 7 gün güncel konu araştır; yeterli kaynak yoksa "
        "son 30 güne genişlet"
    )
    task = Task(action="current research", agent="research", target=command,
                metadata={"market_context": "İsviçre"})

    output = agent.execute(task)

    assert len(agent.manager.calls) == 2
    assert "son 30 gün" in agent.manager.calls[1]
    assert "OTOMATİK 30 GÜNLÜK YEDEK" in output
    assert task.metadata["report"]["sufficient"] is True
    assert task.metadata["report"]["freshness_window_days"] == 30


def test_concise_one_click_wording_also_enables_30_day_fallback():
    command = "İsviçre için son 7 günü tara; iki güvenilir kaynak yoksa 30 güne genişlet."
    assert any(cue in command.casefold() for cue in _WINDOW_FALLBACK_CUES)


def test_selected_headline_gets_one_bounded_same_story_corroboration_pass():
    now = datetime.now(timezone.utc).isoformat()
    headline = "Swiss rail operator announces night-train expansion"

    class _Knowledge:
        rows = {}

        def find_research(self, topic):
            return self.rows.get(topic)

    class _Manager:
        def __init__(self):
            self.knowledge = _Knowledge()
            self.calls = []

        def research(self, topic, **kwargs):
            self.calls.append(topic)
            if "aynı olayı doğrulayan" in topic:
                self.knowledge.rows[topic] = {
                    "summary": f"SEÇİLEN KONU: {headline}", "created_at": now,
                    "sources": [{
                        "title": "Swiss rail night-train expansion confirmed",
                        "summary": "Swiss rail operator confirms the night-train expansion.",
                        "url": "https://www.rts.ch/info/b", "published_at": now,
                    }],
                }
                return "doğrulama taraması tamamlandı"
            if "alternative_source_pass" in topic.casefold():
                self.knowledge.rows[topic] = {
                    "summary": f"SEÇİLEN KONU: {headline}\nİsviçre gündemi",
                    "created_at": now,
                    "sources": [{
                        "title": headline,
                        "summary": "Swiss rail operator announces a night-train expansion.",
                        "url": "https://www.srf.ch/news/a", "published_at": now,
                    }],
                }
                return "30 günlük tarama tamamlandı"
            self.knowledge.rows[topic] = {
                "summary": "SEÇİLEN KONU: sonuç yok\nİsviçre gündemi",
                "created_at": now, "sources": [],
            }
            return "ilk tarama tamamlandı"

    agent = ResearchAgent(); agent.manager = _Manager()
    task = Task(
        action="current research", agent="research",
        target=("İsviçre için son 7 gün içinde aynı haberi doğrulayan en az iki bağımsız "
                "kaynakla güncel gündem"),
        metadata={"market_context": "İsviçre", "allow_30_day_fallback": True},
    )

    output = agent.execute(task)

    assert len(agent.manager.calls) == 3
    assert "OTOMATİK AYNI-HABER KAYNAK DOĞRULAMASI" in output
    assert task.metadata["report"]["sufficient"] is True
    assert len(task.metadata["report"]["supporting_evidence"]) == 2


def test_structured_fallback_survives_clean_research_task_rewrite():
    now = datetime.now(timezone.utc)
    older = (now - timedelta(days=12)).isoformat()

    class _Knowledge:
        rows = {}
        def find_research(self, topic):
            return self.rows.get(topic)

    class _Manager:
        def __init__(self):
            self.knowledge, self.calls = _Knowledge(), []
        def research(self, topic, **kwargs):
            self.calls.append(topic)
            self.knowledge.rows[topic] = {
                "summary": "SEÇİLEN KONU: İsviçre ulaşım gelişmesi",
                "created_at": now.isoformat(),
                "sources": ([
                    {"url": "https://www.srf.ch/news/a", "published_at": older},
                    {"url": "https://www.rts.ch/info/b", "published_at": older},
                ] if "son 30 gün" in topic else []),
            }
            return "ok"

    agent = ResearchAgent(); agent.manager = _Manager()
    task = Task(
        action="current research", agent="research",
        target="İsviçre için son 7 gün güncel gündem",
        metadata={"market_context": "İsviçre", "allow_30_day_fallback": True},
    )
    output = agent.execute(task)
    assert "son 30 gün" in agent.manager.calls[1]
    assert "OTOMATİK 30 GÜNLÜK YEDEK" in output
    assert task.metadata["report"]["freshness_window_days"] == 30


def test_media_research_passes_recent_video_topics_as_exclusions(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()

    class _Knowledge:
        def find_research(self, topic):
            return {"summary": "İsviçre güncel teknoloji haberi", "created_at": now,
                    "sources": [
                        {"url": "https://www.srf.ch/news/schweiz/a", "published_at": now},
                        {"url": "https://www.rts.ch/info/suisse/b", "published_at": now},
                    ]}

    class _Manager:
        knowledge = _Knowledge()

        def __init__(self):
            self.kwargs = {}

        def research(self, topic, **kwargs):
            self.kwargs = kwargs
            return "ok"

    monkeypatch.setattr(ResearchAgent, "_recent_video_topics",
                        staticmethod(lambda limit=8: ["Eski oylama konusu"]))
    agent = ResearchAgent()
    manager = _Manager()
    agent.manager = manager
    task = Task(action="current research", agent="research",
                target="İsviçre güncel teknoloji haberi",
                metadata={"market_context": "İsviçre"})

    agent.execute(task)

    assert manager.kwargs["exclude_topics"] == ["Eski oylama konusu"]


def test_failed_render_selected_topic_is_still_excluded_next_time(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    KnowledgeBase().remember_research(
        topic="İsviçre güncel gündem",
        summary="SEÇİLEN KONU: Aargau kantonu oylama sonuçları\n\nJARVIS Önerisi",
        report_path="workspace/research/a.md", source_count=2,
    )

    topics = ResearchAgent._recent_video_topics()

    assert "Aargau kantonu oylama sonuçları" in topics
