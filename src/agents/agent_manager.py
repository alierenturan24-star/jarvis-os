from src.agents.research_agent import ResearchAgent


class AgentManager:

    def __init__(self):
        self.research_agent = ResearchAgent()

    def find_agent(self, message: str):
        text = message.lower()

        research_words = (
            "araştır",
            "internette ara",
            "webde ara",
            "web'de ara",
            "kaynak bul",
            "hakkında bilgi bul",
            "ücretsiz api bul",
            "yapay zeka şirketlerini kontrol et",
        )

        if any(
            word in text
            for word in research_words
        ):
            return self.research_agent

        return None