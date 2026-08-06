from typing import Any

from ddgs import DDGS

from src.tools.base_tool import BaseTool


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
            raw_results = DDGS().text(
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
    ) -> dict:

        return self.execute(
            query=query,
            max_results=max_results,
        )