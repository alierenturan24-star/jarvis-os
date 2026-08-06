from src.agents.base_agent import BaseAgent
from src.context.prompt_builder import PromptBuilder
from src.council.council import AICouncil
from src.planner.task import Task
from src.providers.provider_manager import TASK_SHORT_CHAT
from src.providers.router import ModelRouter


class ChatAgent(BaseAgent):

    def __init__(self) -> None:
        super().__init__("Chat Agent")
        self.router = ModelRouter()
        self.council = AICouncil()
        self.prompt_builder = PromptBuilder()
        # Sprint 25: son yönlendirme kararının dökümü (gözlemlenebilirlik
        # için; dış davranış/dönüş tipi DEĞİŞMEDİ).
        self.last_route = None

    def health(self) -> dict:
        return {
            "agent": self.name,
            "available": True,
            "providers": self.router.manager.available_names(),
        }

    def execute(self, task: Task) -> str:
        message = task.target.strip()

        if not message:
            return "Boş mesaj gönderildi."

        use_council = any(
            phrase in message.casefold()
            for phrase in [
                "konsey",
                "yapay zekalara sor",
                "yapay zekâlara sor",
                "birden fazla ai",
                "birden fazla yapay zeka",
                "farklı modeller",
            ]
        )

        if use_council:
            decision = self.council.ask(
                message=message,
                max_models=3,
            )
            return (
                f"{decision.final_answer}\n\n"
                f"Konsey güveni: {decision.confidence}/100\n"
                f"Uzlaşı: {decision.agreement}/100"
            )

        # Sprint 19 düzeltmesi: sistem bağlamı (JARVIS kimliği/proje durumu)
        # ile kullanıcının gerçek mesajı AYRI gönderiliyor -- ikisi tek bir
        # düz metinde birleşince küçük yerel model, mesaja cevap vermek
        # yerine bağlamı olduğu gibi geri döküyordu (bkz. Sprint 18 canlı
        # test raporu).
        system_text, user_text = self.prompt_builder.build_system_and_user(
            task=message,
            role="JARVIS kişisel asistanı",
            instructions=[
                "Yalnızca sorulan konuya cevap ver.",
                "Projenin güncel önceliklerini dikkate al.",
                "Bilmediğin veya doğrulayamadığın bilgiyi açıkça belirt.",
                "Cevabın tamamını doğal Türkçe yaz.",
            ],
        )

        # Sprint 25 düzeltmesi: doğrudan ``self.router.ollama`` yerine artık
        # görev-türü karar tablosundan geçiyor ("kısa sohbet" -> Ollama;
        # başarısız olursa otomatik fallback zaten Ollama'ya düşüyor,
        # yani bu görev için pratik davranış AYNI kalıyor, ama artık
        # sessizce sabitlenmiş değil, GÖZLENEBİLİR bir karar).
        self.last_route = self.router.manager.route_and_generate(
            prompt=user_text, task_type=TASK_SHORT_CHAT, system=system_text,
        )
        return self.last_route.output
