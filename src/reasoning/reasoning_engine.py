from dataclasses import dataclass, field


@dataclass
class ReasoningPlan:

    internet: bool = False

    browser: bool = False

    coding: bool = False

    research: bool = False

    planning: bool = False

    finance: bool = False

    media: bool = False

    memory: bool = True

    priority: str = "normal"

    risk: str = "low"

    requires_confirmation: bool = False

    recommended_model: str = "chat"

    agents: list[str] = field(default_factory=list)


class ReasoningEngine:

    def analyze(self, message: str) -> ReasoningPlan:

        text = message.casefold()

        plan = ReasoningPlan()

        # ------------------------
        # RESEARCH
        # ------------------------

        if any(
            keyword in text
            for keyword in (
                "araştır",
                "incele",
                "karşılaştır",
                "analiz et",
            )
        ):

            plan.internet = True
            plan.research = True
            plan.recommended_model = "research"

            plan.agents.append("research")

        # ------------------------
        # BROWSER
        # ------------------------

        if any(
            keyword in text
            for keyword in (
                "google",
                "youtube",
                "github",
                "aç",
            )
        ):

            plan.browser = True

            plan.agents.append("browser")

        # ------------------------
        # CODING
        # ------------------------

        if any(
            keyword in text
            for keyword in (
                "python",
                "kod",
                "debug",
                "programla",
            )
        ):

            plan.coding = True

            plan.recommended_model = "coding"

            plan.agents.append("coding")

        # ------------------------
        # PLANNING
        # ------------------------

        if any(
            keyword in text
            for keyword in (
                "planla",
                "adımlara ayır",
            )
        ):

            plan.planning = True

            plan.agents.append("planning")

        # ------------------------
        # FINANCE
        # ------------------------

        if any(
            keyword in text
            for keyword in (
                "borsa",
                "bitcoin",
                "btc",
                "eth",
                "coin",
                "kripto",
            )
        ):

            plan.finance = True

            plan.internet = True

            plan.recommended_model = "research"

        # ------------------------
        # MEDIA
        # ------------------------

        if any(
            keyword in text
            for keyword in (
                "youtube videosu",
                "thumbnail",
                "video üret",
            )
        ):

            plan.media = True

        # ------------------------
        # RISK
        # ------------------------

        if any(
            keyword in text
            for keyword in (
                "sil",
                "format",
                "delete",
                "rm ",
            )
        ):

            plan.risk = "high"

            plan.requires_confirmation = True

        return plan