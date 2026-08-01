from dataclasses import dataclass


@dataclass
class Decision:

    intent: str

    risk: str

    internet: bool

    confirmation: bool

    model: str

    agents: list[str]


class DecisionEngine:

    def analyze(self, message: str) -> Decision:

        text = message.lower()

        decision = Decision(
            intent="chat",
            risk="low",
            internet=False,
            confirmation=False,
            model="ollama",
            agents=[]
        )

        if any(x in text for x in [
            "araştır",
            "incele",
            "karşılaştır",
        ]):

            decision.intent = "research"
            decision.internet = True
            decision.agents.append("research")

        if any(x in text for x in [
            "google",
            "youtube",
            "github",
            "aç",
        ]):

            decision.intent = "browser"
            decision.agents.append("browser")

        if any(x in text for x in [
            "sil",
            "format",
            "kaldır",
            "delete",
        ]):

            decision.risk = "high"
            decision.confirmation = True

        return decision