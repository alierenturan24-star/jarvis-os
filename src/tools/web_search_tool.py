from src.tools.base_tool import BaseTool

import requests


class WebSearchTool(BaseTool):

    def __init__(self):

        super().__init__(
            name="Web Search",
            description="İnternette arama yapar.",
            requires_confirmation=False,
        )

    def execute(self, **kwargs):

        query = kwargs.get("query", "")

        if not query:

            return "Arama metni boş."

        try:

            url = "https://duckduckgo.com/?q=" + query.replace(" ", "+")

            return f"Arama bağlantısı:\n{url}"

        except Exception as e:

            return f"Hata: {e}"