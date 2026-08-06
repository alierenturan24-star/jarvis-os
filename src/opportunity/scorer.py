from dataclasses import dataclass


@dataclass
class OpportunityScore:
    total: int
    relevance: int
    accessibility: int
    cost_advantage: int
    income_potential: int
    risk: int


class OpportunityScorer:

    POSITIVE_WORDS = {
        "free",
        "ücretsiz",
        "open source",
        "açık kaynak",
        "api",
        "credit",
        "kredi",
        "affiliate",
        "automation",
        "otomasyon",
        "creator",
        "video",
        "ai",
        "yapay zeka",
        "saas",
    }

    RISK_WORDS = {
        "guaranteed",
        "garanti kazanç",
        "get rich",
        "hızlı zengin",
        "deposit",
        "para yatır",
        "casino",
        "bahis",
        "scam",
        "dolandırıcılık",
    }

    def score(self, opportunity: dict) -> OpportunityScore:

        text = (
            f"{opportunity.get('title', '')} "
            f"{opportunity.get('summary', '')}"
        ).casefold()

        positive_matches = sum(
            1
            for word in self.POSITIVE_WORDS
            if word in text
        )

        risk_matches = sum(
            1
            for word in self.RISK_WORDS
            if word in text
        )

        relevance = min(
            100,
            40 + positive_matches * 8,
        )

        accessibility = 75 if any(
            word in text
            for word in [
                "free",
                "ücretsiz",
                "open source",
                "açık kaynak",
            ]
        ) else 55

        cost_advantage = 85 if any(
            word in text
            for word in [
                "free",
                "ücretsiz",
                "credit",
                "open source",
            ]
        ) else 50

        income_potential = min(
            90,
            35 + positive_matches * 7,
        )

        risk = min(
            100,
            15 + risk_matches * 30,
        )

        total = round(
            relevance * 0.30
            + accessibility * 0.20
            + cost_advantage * 0.20
            + income_potential * 0.25
            + (100 - risk) * 0.05
        )

        return OpportunityScore(
            total=total,
            relevance=relevance,
            accessibility=accessibility,
            cost_advantage=cost_advantage,
            income_potential=income_potential,
            risk=risk,
        )

    def rank(
        self,
        opportunities: list[dict],
        limit: int = 10,
    ) -> list[dict]:

        scored = []

        for opportunity in opportunities:

            score = self.score(opportunity)

            scored.append(
                {
                    **opportunity,
                    "score": score.total,
                    "relevance": score.relevance,
                    "accessibility": score.accessibility,
                    "cost_advantage": score.cost_advantage,
                    "income_potential": score.income_potential,
                    "risk": score.risk,
                }
            )

        scored.sort(
            key=lambda item: (
                item["score"],
                -item["risk"],
            ),
            reverse=True,
        )

        return scored[:limit]