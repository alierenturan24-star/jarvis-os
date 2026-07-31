import html
import re
import urllib.parse
import urllib.request

from src.tools.base_tool import BaseTool


class WebSearchTool(BaseTool):

    def __init__(self):
        super().__init__(
            name="Web Search Tool",
            description="İnternette bilgi ve kaynak arar",
            requires_confirmation=False,
        )

    def execute(self, **kwargs):
        query = kwargs.get("query", "").strip()
        max_results = kwargs.get("max_results", 5)

        if not query:
            return "Arama konusu belirtilmedi."

        return self.search(query, max_results)

    def search(self, query: str, max_results: int = 5) -> str:
        try:
            encoded_query = urllib.parse.quote_plus(query)

            url = (
                "https://html.duckduckgo.com/html/"
                f"?q={encoded_query}"
            )

            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 "
                        "(Windows NT 10.0; Win64; x64)"
                    )
                },
            )

            with urllib.request.urlopen(
                request,
                timeout=15,
            ) as response:
                page = response.read().decode(
                    "utf-8",
                    errors="replace",
                )

            pattern = (
                r'class="result__a"[^>]*href="([^"]+)"[^>]*>'
                r'(.*?)</a>'
            )

            matches = re.findall(
                pattern,
                page,
                flags=re.IGNORECASE | re.DOTALL,
            )

            results = []

            for link, title in matches[:max_results]:
                clean_title = re.sub(
                    r"<[^>]+>",
                    "",
                    title,
                )

                clean_title = html.unescape(
                    clean_title
                ).strip()

                clean_link = html.unescape(link)

                if "uddg=" in clean_link:
                    parsed = urllib.parse.urlparse(
                        clean_link
                    )

                    parameters = urllib.parse.parse_qs(
                        parsed.query
                    )

                    clean_link = parameters.get(
                        "uddg",
                        [clean_link],
                    )[0]

                results.append(
                    f"{len(results) + 1}. {clean_title}\n"
                    f"Kaynak: {clean_link}"
                )

            if not results:
                return (
                    "Arama yapıldı ancak uygun sonuç "
                    "bulunamadı."
                )

            return (
                f"Arama konusu: {query}\n\n"
                + "\n\n".join(results)
            )

        except Exception as error:
            return f"Web arama hatası: {error}"