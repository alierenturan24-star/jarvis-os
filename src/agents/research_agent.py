from src.tools.web_search_tool import WebSearchTool


class ResearchAgent:

    def __init__(self):
        self.search = WebSearchTool()

    def execute(self, command):

        query = (
            command
            .replace("araştır", "")
            .replace("araştırır mısın", "")
            .strip()
        )

        return self.search.search(query)