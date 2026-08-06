from src.council.consensus import ConsensusEngine
from src.council.cost_advisor import CouncilCostAdvisor
from src.council.models import (
    CouncilDecision,
    CouncilResponse,
    ModelProfile,
)
from src.council.selector import CouncilSelector
from src.context.prompt_builder import PromptBuilder
from src.providers.cost_optimizer import ModelDecision
from src.providers.provider_manager import ProviderManager


class AICouncil:

    def __init__(self) -> None:

        self.selector = CouncilSelector()
        self.consensus = ConsensusEngine()
        self.provider_manager = ProviderManager()
        self.prompt_builder = PromptBuilder()
        self.cost_advisor = CouncilCostAdvisor(self.provider_manager)

    def _build_prompt(
        self,
        message: str,
        profile: ModelProfile,
    ) -> str:
        strengths = ", ".join(profile.strengths)

        return self.prompt_builder.build(
            task=message,
            role=f"JARVIS AI Konseyi üyesi: {profile.name}",
            instructions=[
                f"Uzmanlık alanların: {strengths}.",
                "Görevi uzmanlık alanına göre değerlendir.",
                "Varsayımlarını ve önemli riskleri açıkça belirt.",
                "Kesin olmayan bilgiyi kesinmiş gibi sunma.",
                "Cevabın tamamını doğal Türkçe yaz.",
            ],
        )

    def _ask_model(
        self,
        message: str,
        profile: ModelProfile,
    ) -> CouncilResponse:

        prompt = self._build_prompt(
            message=message,
            profile=profile,
        )

        try:

            answer = self.provider_manager.generate(
                prompt,
                profile.provider,
                profile.model,
            )

            failed_messages = [
                "zaman aşımına uğradı",
                "bulunamadı",
                "hata verdi",
                "model cevap üretmedi",
            ]

            success = not any(
                text in answer.casefold()
                for text in failed_messages
            )

            return CouncilResponse(
                model_name=profile.name,
                provider=profile.provider,
                answer=answer if success else "",
                success=success,
                confidence=70 if success else 0,
                error="" if success else answer,
                priority=profile.priority,
            )

        except Exception as error:

            return CouncilResponse(
                model_name=profile.name,
                provider=profile.provider,
                answer="",
                success=False,
                confidence=0,
                error=str(error),
                priority=profile.priority,
            )

    def ask(
        self,
        message: str,
        max_models: int = 3,
    ) -> CouncilDecision:

        selected_models, task_type = self.selector.choose(
            message=message,
            max_models=max_models,
        )

        if not selected_models:

            return CouncilDecision(
                final_answer=(
                    "AI Konseyi için aktif model bulunamadı."
                ),
                confidence=0,
                agreement=0,
                responses=[],
                task_type=task_type,
            )

        responses = [
            self._ask_model(message, profile)
            for profile in selected_models
        ]

        return self.consensus.decide(responses, task_type=task_type)

    def suggest_model(self, message: str) -> ModelDecision:
        """Maliyet-optimize edilmiş tekil model önerisi döndürür.

        ``ask()``'in çoklu-model konsey akışından bağımsızdır; en düşük
        maliyetli ama yeterli tek modeli ve seçim nedenini raporlamak
        isteyen çağıranlar için eklenmiştir (ör. maliyet raporlama).
        """
        return self.cost_advisor.advise(message)
