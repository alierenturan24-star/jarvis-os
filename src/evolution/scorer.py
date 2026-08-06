from dataclasses import dataclass


@dataclass(frozen=True)
class ImprovementScore:
    total: int
    goal_fit: int
    safety: int
    implementation_ease: int
    cost_advantage: int
    expected_value: int


class EvolutionScorer:
    """Bulunan araçları kullanıcının hedefleri ve güvenlik açısından puanlar."""

    POSITIVE_TERMS = {
        "open source",
        "açık kaynak",
        "free",
        "ücretsiz",
        "local",
        "yerel",
        "python",
        "agent",
        "automation",
        "otomasyon",
        "security",
        "güvenlik",
        "observability",
        "ollama",
        "video",
        "finance",
        "research",
    }

    HIGH_RISK_TERMS = {
        "download and run",
        "curl | sh",
        "disable security",
        "bypass",
        "crack",
        "guaranteed profit",
        "garanti kazanç",
        "seed phrase",
        "private key",
    }

    def score(self, item: dict) -> ImprovementScore:
        text = (
            f"{item.get('title', '')} {item.get('summary', '')}"
        ).casefold()

        positive_count = sum(
            1 for term in self.POSITIVE_TERMS if term in text
        )
        risk_count = sum(
            1 for term in self.HIGH_RISK_TERMS if term in text
        )

        goal_fit = min(100, 35 + positive_count * 8)
        safety = max(5, 90 - risk_count * 35)
        implementation_ease = 75 if any(
            term in text
            for term in ["python", "open source", "açık kaynak", "api"]
        ) else 55
        cost_advantage = 90 if any(
            term in text
            for term in ["free", "ücretsiz", "open source", "açık kaynak"]
        ) else 55
        expected_value = min(95, 40 + positive_count * 7)

        total = round(
            goal_fit * 0.30
            + safety * 0.25
            + implementation_ease * 0.15
            + cost_advantage * 0.15
            + expected_value * 0.15
        )

        return ImprovementScore(
            total=total,
            goal_fit=goal_fit,
            safety=safety,
            implementation_ease=implementation_ease,
            cost_advantage=cost_advantage,
            expected_value=expected_value,
        )

    def rank(self, items: list[dict], limit: int = 8) -> list[dict]:
        ranked: list[dict] = []

        for item in items:
            score = self.score(item)
            ranked.append(
                {
                    **item,
                    "score": score.total,
                    "goal_fit": score.goal_fit,
                    "safety": score.safety,
                    "implementation_ease": score.implementation_ease,
                    "cost_advantage": score.cost_advantage,
                    "expected_value": score.expected_value,
                }
            )

        ranked.sort(
            key=lambda item: (item["score"], item["safety"]),
            reverse=True,
        )
        return ranked[:limit]
