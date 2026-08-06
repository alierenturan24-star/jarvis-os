from src.tools.web_search_tool import WebSearchTool


class FinanceCollector:

    def __init__(self) -> None:
        self.web = WebSearchTool()

    def collect(
        self,
        asset: str,
        max_results_per_query: int = 4,
    ) -> list[dict]:

        queries = [
            f"{asset} latest news",
            f"{asset} market analysis",
            f"{asset} risk outlook",
            f"{asset} price forecast",
        ]

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
                        "title": str(
                            item.get("title", "")
                        ).strip(),
                        "url": url,
                        "summary": str(
                            item.get("summary", "")
                        ).strip(),
                    }
                )

        return collected