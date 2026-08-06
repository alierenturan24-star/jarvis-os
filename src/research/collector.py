from src.tools.web_search_tool import WebSearchTool


class ResearchCollector:

    def __init__(self) -> None:
        self.web = WebSearchTool()

    def collect(
        self,
        topic: str,
        max_results_per_source: int = 3,
    ) -> list[dict]:

        searches = [
            {
                "source": "Genel Web",
                "query": topic,
            },
            {
                "source": "GitHub",
                "query": f"site:github.com {topic}",
            },
            {
                "source": "Arxiv",
                "query": f"site:arxiv.org {topic}",
            },
            {
                "source": "Hacker News",
                "query": f"site:news.ycombinator.com {topic}",
            },
        ]

        collected: list[dict] = []
        known_urls: set[str] = set()

        for search in searches:

            result = self.web.search(
                query=search["query"],
                max_results=max_results_per_source,
            )

            if not result.get("success"):
                continue

            for item in result.get("results", []):

                url = str(item.get("url", "")).strip()

                if not url or url in known_urls:
                    continue

                known_urls.add(url)

                collected.append(
                    {
                        "source": search["source"],
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