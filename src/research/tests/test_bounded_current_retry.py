from datetime import datetime, timezone

from src.agents.research_agent import ResearchAgent
from src.planner.task import Task


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
