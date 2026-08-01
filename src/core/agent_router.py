from src.agents.browser_agent import BrowserAgent
from src.agents.research_agent import ResearchAgent


class AgentRouter:

    def __init__(self):

        self.agents = {
            "browser": BrowserAgent(),
            "research": ResearchAgent(),
        }

    def execute(self, task):

        agent = self.agents.get(task.agent)

        if not agent:
            return f"Agent bulunamadı: {task.agent}"

        return agent.execute(task.target or task.action)