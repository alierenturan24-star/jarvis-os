from src.agents.base_agent import BaseAgent
from src.tools.web_search_tool import WebSearchTool


class ResearchAgent(BaseAgent):

    def __init__(self):
        super().__init__("Research Agent")
        self.web_search = WebSearchTool()

    def execute(self, task: str) -> str:
        search_result = self.web_search.execute(
            query=task,
            max_results=5,
        )

        return (
            "=== ARAŞTIRMA RAPORU ===\n\n"
            f"{search_result}"
        )