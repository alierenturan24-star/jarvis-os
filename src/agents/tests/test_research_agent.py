from __future__ import annotations

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
