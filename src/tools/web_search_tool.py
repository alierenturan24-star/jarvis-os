from urllib.parse import quote_plus
import webbrowser

from src.tools.base_tool import BaseTool


class WebSearchTool(BaseTool):

    def __init__(self):

        super().__init__(
            name="Web Search",
            description="İnternette arama yapar.",
            requires_confirmation=False,
        )

    def execute(self, **kwargs):

        query = kwargs.get("query")

        if not query:

            return "Arama metni boş."

        url = (
            "https://duckduckgo.com/?q="
            + quote_plus(query)
        )

        webbrowser.open(url)

        return f"Arama başlatıldı:\n{query}"

    # ResearchAgent için uyumluluk
    def search(self, query):

        return self.execute(query=query)