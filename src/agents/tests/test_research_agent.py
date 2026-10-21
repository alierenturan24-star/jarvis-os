from __future__ import annotations

from datetime import datetime, timezone

from src.agents.research_agent import ResearchAgent
from src.planner.task import Task
from src.providers.provider_manager import ProviderManager, RouteResult
from src.research.manager import ResearchManager
from src.tools.web_search_tool import WebSearchTool


def _route_result(output: str) -> RouteResult:
    return RouteResult(
        output=output, chosen_provider="ollama", provider_used="ollama", reason="test",
        fallback_used=False, duration_seconds=0.1, success=True,
    )


class TestResearchAgentLocalCodeRouting:
    """Sprint 41 TEST F/G: JARVIS'in kendi kodu hakkındaki sorular WEB
    araması yapmadan, sınırlı yerel bağlamla cevaplanmalı."""

    def test_local_code_query_never_touches_web_search(self, monkeypatch):
        web_calls = []
        monkeypatch.setattr(WebSearchTool, "search", lambda self, *a, **k: web_calls.append(1) or {"success": False, "results": []})
        research_calls = []
        monkeypatch.setattr(ResearchManager, "research", lambda self, *a, **k: research_calls.append(1) or "web sonucu")

        captured_prompts = []
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: captured_prompts.append(prompt) or _route_result("analiz"),
        )

        agent = ResearchAgent()
        task = Task(
            agent="research", action="dispatch",
            target="Jarvis, bu projenin provider routing mimarisini incele. "
                   "CostOptimizer, AIStrategyEngine ve ProviderManager arasındaki "
                   "gerçek çağrı zincirini proje kodundan bul. İnternette araştırma yapma.",
        )

        result = agent.execute(task)

        assert web_calls == []  # WebSearchTool HİÇ çağrılmadı
        assert research_calls == []  # ResearchManager.research (web akışı) HİÇ çağrılmadı
        assert "internet KULLANILMADI" in result
        assert len(captured_prompts) == 1

    def test_context_sent_to_llm_is_bounded_not_the_whole_repository(self, monkeypatch):
        # TEST G: tüm repository LLM prompt'una BASILMAMALI.
        captured_prompts = []
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: captured_prompts.append(prompt) or _route_result("analiz"),
        )

        agent = ResearchAgent()
        task = Task(agent="research", action="dispatch", target="CostOptimizer ve ProviderManager arasındaki ilişkiyi anlat.")
        agent.execute(task)

        assert len(captured_prompts) == 1
        # Repo onlarca dosya / yüz binlerce karakter içerir -- bağlam
        # bunun küçük bir kesri olmalı (birkaç sınıf kaynağı + istem metni).
        assert len(captured_prompts[0]) < 10_000

    def test_ordinary_query_still_uses_real_web_research_unaffected(self, monkeypatch):
        # Regresyon: yerel kod sinyali OLMAYAN sıradan bir araştırma isteği
        # eskisi gibi ResearchManager'a gitmeli -- davranış BOZULMADI.
        research_calls = []
        monkeypatch.setattr(
            ResearchManager, "research",
            lambda self, topic, force_refresh=False, preferred_provider=None: research_calls.append(topic) or "ok (test)",
        )

        agent = ResearchAgent()
        task = Task(agent="research", action="dispatch", target="Bitcoin neden düştü, araştır.")
        result = agent.execute(task)

        assert research_calls  # ResearchManager.research GERÇEKTEN çağrıldı
        assert result == "ok (test)"


def test_media_research_tries_next_headline_when_first_candidate_has_one_source(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()

    class _Knowledge:
        def __init__(self):
            self.records = {}

        def find_research(self, topic):
            return self.records.get(topic)

    class _Manager:
        def __init__(self):
            self.knowledge = _Knowledge()
            self.calls = []

        def research(self, topic, **kwargs):
            self.calls.append(topic)
            if "ALTERNATIVE_SOURCE_PASS" in topic:
                self.knowledge.records[topic] = {
                    "summary": "SEÇİLEN KONU: Swiss football result",
                    "created_at": now,
                    "sources": [
                        {
                            "title": "Swiss football result",
                            "summary": "Switzerland won a football match.",
                            "url": "https://www.rts.ch/sport/football/a",
                            "published_at": now,
                            "source_language": "fr",
                        },
                        {
                            "title": "Swiss AI talent exodus accelerates",
                            "summary": "Swiss AI researchers are being recruited by global technology companies.",
                            "url": "https://www.nzz.ch/technology/ai-talent-b",
                            "published_at": now,
                            "source_language": "de",
                        },
                    ],
                }
                return self.knowledge.records[topic]["summary"]

            if '"Swiss football result"' in topic:
                self.knowledge.records[topic] = {
                    "summary": "SEÇİLEN KONU: Swiss football result",
                    "created_at": now,
                    "sources": [{
                        "title": "Swiss football result",
                        "summary": "Switzerland won a football match.",
                        "url": "https://www.rts.ch/sport/football/a",
                        "published_at": now,
                    }],
                }
                return self.knowledge.records[topic]["summary"]

            if '"Swiss AI talent exodus accelerates"' in topic:
                self.knowledge.records[topic] = {
                    "summary": "SEÇİLEN KONU: Swiss AI talent exodus accelerates",
                    "created_at": now,
                    "sources": [
                        {
                            "title": "Swiss AI talent exodus accelerates",
                            "summary": "Swiss AI researchers are being recruited by global technology companies.",
                            "url": "https://www.nzz.ch/technology/ai-talent-b",
                            "published_at": now,
                        },
                        {
                            "title": "Big Tech recruits Swiss AI talent",
                            "summary": "Global technology companies are recruiting leading Swiss AI researchers.",
                            "url": "https://www.swissinfo.ch/eng/science/ai-talent-b",
                            "published_at": now,
                        },
                    ],
                }
                return self.knowledge.records[topic]["summary"]

            self.knowledge.records[topic] = {
                "summary": "Kaynaklardan güvenilir bir özet oluşturulamadı.",
                "created_at": now,
                "sources": [],
            }
            return self.knowledge.records[topic]["summary"]

    agent = ResearchAgent()
    agent.manager = _Manager()
    monkeypatch.setattr(ResearchAgent, "_recent_video_topics", staticmethod(lambda limit=8: []))
    task = Task(
        agent="research",
        action="dispatch",
        target=(
            "İsviçre için son 7 gün içinde güvenilir aynı haberi doğrulayan en az iki bağımsız "
            "kaynakla güncel gündem araştır"
        ),
        metadata={
            "market_context": "İsviçre",
            "allow_30_day_fallback": True,
            "preferred_ai_provider": "gemini",
        },
    )

    agent.execute(task)

    report = task.metadata["report"]
    assert report["sufficient"] is True
    assert report["selected_topic"] == "Swiss AI talent exodus accelerates"
    assert len(report["supporting_evidence"]) >= 2
    assert any('"Swiss football result"' in call for call in agent.manager.calls)
    assert any('"Swiss AI talent exodus accelerates"' in call for call in agent.manager.calls)


def test_recent_video_topics_ignore_failed_research_only_history(monkeypatch):
    monkeypatch.setattr(
        "src.control_center.store.ControlCenterStore.snapshot",
        lambda self: {
            "youtube_learning": {
                "productions": [
                    {"topic": "Actually produced Swiss video"},
                ]
            },
            "channels": {},
        },
    )
    monkeypatch.setattr(
        "src.knowledge.knowledge_base.KnowledgeBase.recent_research",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("failed research history must not participate in repeat blocking")
        ),
    )

    topics = ResearchAgent._recent_video_topics()

    assert topics == ["Actually produced Swiss video"]
