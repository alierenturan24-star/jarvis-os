from dataclasses import dataclass


@dataclass
class FinanceRiskResult:
    risk_score: int
    opportunity_score: int
    sentiment_score: int
    warning_count: int


class FinanceRiskEngine:

    POSITIVE_WORDS = {
        "growth",
        "büyüme",
        "profit",
        "kâr",
        "adoption",
        "benimsenme",
        "partnership",
        "ortaklık",
        "upgrade",
        "yükseliş",
        "strong",
        "bullish",
    }

    NEGATIVE_WORDS = {
        "loss",
        "zarar",
        "lawsuit",
        "dava",
        "hack",
        "hacked",
        "ban",
        "yasak",
        "decline",
        "düşüş",
        "risk",
        "warning",
        "bearish",
        "fraud",
        "dolandırıcılık",
    }

    def analyze(
        self,
        results: list[dict],
    ) -> FinanceRiskResult:

        text = " ".join(
            (
                f"{item.get('title', '')} "
                f"{item.get('summary', '')}"
            )
            for item in results
        ).casefold()

        positive_count = sum(
            1
            for word in self.POSITIVE_WORDS
            if word in text
        )

        negative_count = sum(
            1
            for word in self.NEGATIVE_WORDS
            if word in text
        )

        sentiment_score = max(
            0,
            min(
                100,
                50 + positive_count * 7 - negative_count * 9,
            ),
        )

        risk_score = max(
            10,
            min(
                100,
                30 + negative_count * 10 - positive_count * 3,
            ),
        )

        opportunity_score = max(
            0,
            min(
                100,
                round(
                    sentiment_score * 0.55
                    + (100 - risk_score) * 0.45
                ),
            ),
        )

        return FinanceRiskResult(
            risk_score=risk_score,
            opportunity_score=opportunity_score,
            sentiment_score=sentiment_score,
            warning_count=negative_count,
        )