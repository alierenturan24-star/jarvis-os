from typing import Any

from ddgs import DDGS

from src.config.settings import Settings
from src.tools.base_tool import BaseTool

# Sprint: research/production pipeline audit -- now configurable/bounded via
# Settings.RESEARCH_PROVIDER_TIMEOUT_SECONDS (same fail-closed _env_float
# pattern as CLAUDE_CODE_TIMEOUT_SECONDS); this alias is kept so existing
# callers importing the module-level constant keep working.
WEB_SEARCH_TIMEOUT_SECONDS = Settings.RESEARCH_PROVIDER_TIMEOUT_SECONDS


class WebSearchTool(BaseTool):

    def __init__(self) -> None:
        super().__init__(
            name="Web Search",
            description="İnternetten gerçek arama sonuçları toplar.",
            requires_confirmation=False,
        )

    def execute(self, **kwargs: Any) -> dict:

        query = str(kwargs.get("query", "")).strip()
        max_results = int(kwargs.get("max_results", 5))

        if not query:
            return {
                "success": False,
                "query": "",
                "results": [],
                "message": "Arama metni boş.",
            }

        try:
            # DDGS'nin istemci timeout'u verilmezse DNS/ağ katmanında
            # sınırsız bekleyebilir. Hata mevcut güvenli sonuç yoluna düşer.
            requested_timeout = float(kwargs.get("timeout_seconds", WEB_SEARCH_TIMEOUT_SECONDS))
            timeout = max(0.01, min(WEB_SEARCH_TIMEOUT_SECONDS, requested_timeout))
            raw_results = DDGS(timeout=timeout).text(
                query,
                region="tr-tr",
                safesearch="moderate",
                max_results=max_results,
            )

            results = []

            for item in raw_results or []:
                results.append(
                    {
                        "title": str(item.get("title", "")).strip(),
                        "url": str(
                            item.get("href")
                            or item.get("url")
                            or ""
                        ).strip(),
                        "summary": str(
                            item.get("body")
                            or item.get("snippet")
                            or ""
                        ).strip(),
                    }
                )

            if not results:
                return {
                    "success": False,
                    "query": query,
                    "results": [],
                    "message": "Arama sonucu bulunamadı.",
                }

            return {
                "success": True,
                "query": query,
                "results": results,
                "message": f"{len(results)} arama sonucu bulundu.",
            }

        except Exception as error:
            return {
                "success": False,
                "query": query,
                "results": [],
                "message": f"Web araması başarısız: {error}",
            }

    def search(
        self,
        query: str,
        max_results: int = 5,
        timeout_seconds: float = WEB_SEARCH_TIMEOUT_SECONDS,
    ) -> dict:

        return self.execute(
            query=query,
            max_results=max_results,
            timeout_seconds=timeout_seconds,
        )
