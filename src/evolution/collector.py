from src.tools.web_search_tool import WebSearchTool


class EvolutionCollector:
    """JARVIS'i geliştirebilecek güncel araç ve yöntemleri toplar."""

    def __init__(self) -> None:
        self.web = WebSearchTool()

    def collect(
        self,
        focus: str = "",
        max_results_per_query: int = 3,
        *,
        broad: bool = True,
    ) -> list[dict]:
        """``broad=True`` (varsayılan, eski davranış DEĞİŞMEDİ): ``focus``
        VARSA bile 5 sabit genel AI-ekosistemi sorgusu HER ZAMAN çalışır.

        Sprint 42 (GOAL-DRIVEN DISCOVERY): ``broad=False`` -- yalnızca
        ``focus`` sorgusu çalışır, 5 sabit sorgu ATLANIR. Bir Mission'ın
        hedefiyle İLGİSİZ geniş bir AI-dünyası taraması YAPILMAMASI
        gerektiğinde (ör. YouTube video üretimi eksikse yalnızca video/
        TTS araçları aranır, finans/coding AI'ları ARANMAZ) kullanılır.
        Yeni bir arama motoru İCAT EDİLMEDİ -- aynı ``WebSearchTool``
        çağrısı, yalnızca hangi sorguların çalıştığı daraltıldı.
        """

        focus = focus.strip()

        if not broad:
            if not focus:
                return []
            queries = [focus]
        else:
            queries = [
                "new open source AI agent tools GitHub",
                "new free AI API credits developer tools",
                "Python AI agent observability security tools",
                "local LLM Ollama agent automation tools",
                "AI video automation open source tools",
            ]

            if focus:
                queries.insert(0, focus)

        collected: list[dict] = []
        known_urls: set[str] = set()

        for query in queries:
            search_result = self.web.search(
                query=query,
                max_results=max_results_per_query,
            )

            if not search_result.get("success"):
                continue

            for item in search_result.get("results", []):
                url = str(item.get("url", "")).strip()

                if not url or url in known_urls:
                    continue

                known_urls.add(url)
                collected.append(
                    {
                        "query": query,
                        "title": str(item.get("title", "")).strip(),
                        "url": url,
                        "summary": str(item.get("summary", "")).strip(),
                    }
                )

        return collected
