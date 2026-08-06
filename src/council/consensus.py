from src.council.models import (
    CouncilDecision,
    CouncilResponse,
)


class ConsensusEngine:
    """Konsey üyelerinin cevaplarını tek bir karara indirger.

    Not: Bu sürüm modeller arası gerçek anlamsal uzlaşı/çelişki tespiti
    yapmıyor (bu, ayrı bir sprintin konusu). Burada hazırlanan altyapı:
    görev tipi bilgisinin (`task_type`) karara taşınması ve öncelik
    (priority) ağırlıklı güven skoru hesaplanabilmesi. Varsayılan davranış
    (basit ortalama) korunur; ağırlıklı hesap yalnızca açıkça istenirse
    (`use_priority_weighting=True`) devreye girer.
    """

    def decide(
        self,
        responses: list[CouncilResponse],
        task_type: str = "",
        use_priority_weighting: bool = False,
    ) -> CouncilDecision:

        successful = [
            response
            for response in responses
            if response.success
            and response.answer.strip()
        ]

        if not successful:

            errors = "\n".join(
                response.error
                for response in responses
                if response.error
            )

            return CouncilDecision(
                final_answer=(
                    "AI Konseyi cevap üretemedi.\n"
                    f"{errors}"
                ),
                confidence=0,
                agreement=0,
                responses=responses,
                task_type=task_type,
            )

        if len(successful) == 1:

            response = successful[0]

            return CouncilDecision(
                final_answer=response.answer,
                confidence=response.confidence,
                agreement=100,
                responses=responses,
                task_type=task_type,
            )

        answers = []

        for index, response in enumerate(
            successful,
            start=1,
        ):
            answers.append(
                f"""### Görüş {index}: {response.model_name}

{response.answer}
"""
            )

        if use_priority_weighting:
            confidence = self._weighted_confidence(successful)
        else:
            confidence = round(
                sum(
                    response.confidence
                    for response in successful
                )
                / len(successful)
            )

        agreement = min(
            95,
            55 + len(successful) * 10,
        )

        return CouncilDecision(
            final_answer=(
                "AI Konseyi görüşleri:\n\n"
                + "\n".join(answers)
            ),
            confidence=confidence,
            agreement=agreement,
            responses=responses,
            task_type=task_type,
        )

    @staticmethod
    def _weighted_confidence(successful: list[CouncilResponse]) -> int:
        """Öncelik (priority) ağırlıklı ortalama güven skoru.

        Hazırlık altyapısıdır: gerçek modeller arası uzlaşı/çelişki
        analizi değildir, yalnızca yüksek öncelikli modellerin güven
        skoruna daha fazla ağırlık verir.
        """

        total_weight = sum(max(response.priority, 1) for response in successful)

        if total_weight == 0:
            return round(sum(r.confidence for r in successful) / len(successful))

        weighted_sum = sum(
            response.confidence * max(response.priority, 1)
            for response in successful
        )

        return round(weighted_sum / total_weight)
