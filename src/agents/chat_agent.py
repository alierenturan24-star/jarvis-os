from src.agents.base_agent import BaseAgent
from src.context.prompt_builder import PromptBuilder
from src.council.council import AICouncil
from src.planner.task import Task
from src.providers.provider_manager import TASK_SHORT_CHAT
from src.providers.router import ModelRouter
import json
import re


_TURKISH_MONTHS = {
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
}


class ChatAgent(BaseAgent):

    @staticmethod
    def _requests_runtime_facts(message: str) -> bool:
        text = message.casefold()
        return any(cue in text for cue in (
            "bugün", "tarih", "saat dilimi", "yerel saat", "sistem durum",
            "runtime", "işlem kimliği", "pid",
        ))

    @staticmethod
    def _runtime_fact_conflict(output: str, context: dict) -> bool:
        expected_date = str(context.get("local_date") or "")
        for candidate in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", output):
            if expected_date and candidate != expected_date:
                return True
        for day, month, year in re.findall(
            r"\b(\d{1,2})\s+(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s+(\d{4})\b",
            output, flags=re.IGNORECASE,
        ):
            month_number = _TURKISH_MONTHS[month.casefold()]
            candidate = f"{int(year):04d}-{month_number:02d}-{int(day):02d}"
            if expected_date and candidate != expected_date:
                return True
        expected_pid = context.get("runtime_pid")
        for candidate in re.findall(
            r"(?:runtime_pid|\bpid\b|işlem kimliği)\D{0,20}(\d+)", output,
            flags=re.IGNORECASE,
        ):
            if expected_pid is not None and int(candidate) != int(expected_pid):
                return True
        state_match = re.search(r"runtime_state\s*[:=]\s*([A-Z_]+)", output, re.IGNORECASE)
        if state_match and context.get("runtime_state"):
            if state_match.group(1).upper() != str(context["runtime_state"]).upper():
                return True
        return False

    @classmethod
    def _ground_runtime_response(cls, output: str, context: dict) -> str:
        facts = (
            "Doğrulanmış runtime gerçekleri: "
            f"yerel tarih/saat={context.get('local_datetime', 'bilinmiyor')}; "
            f"saat dilimi={context.get('timezone', 'bilinmiyor')}; "
            f"PID={context.get('runtime_pid', 'bilinmiyor')}; "
            f"runtime_state={context.get('runtime_state', 'bilinmiyor')}; "
            f"başlangıç={context.get('runtime_started_at', 'bilinmiyor')}; "
            f"son görev={context.get('last_mission_status') or 'bilinmiyor'}; "
            f"son hata={context.get('last_error') or 'yok'}.")
        if cls._runtime_fact_conflict(output, context):
            return facts + "\nModel açıklaması authoritative runtime gerçekleriyle çeliştiği için gösterilmedi."
        return facts + "\n" + output.strip()

    def __init__(self) -> None:
        super().__init__("Chat Agent")
        self.router = ModelRouter()
        self.council = AICouncil()
        self.prompt_builder = PromptBuilder()
        # Sprint 25: son yönlendirme kararının dökümü (gözlemlenebilirlik
        # için; dış davranış/dönüş tipi DEĞİŞMEDİ).
        self.last_route = None
        self.runtime_context_provider = None

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
        runtime_context = (
            self.runtime_context_provider() if callable(self.runtime_context_provider) else {}
        )
        system_text, user_text = self.prompt_builder.build_system_and_user(
            task=message,
            role="JARVIS kişisel asistanı",
            instructions=[
                "Yalnızca sorulan konuya cevap ver.",
                "Projenin güncel önceliklerini dikkate al.",
                "Bilmediğin veya doğrulayamadığın bilgiyi açıkça belirt.",
                "Cevabın tamamını doğal Türkçe yaz.",
                "Tarih/saat ve JARVIS sistem durumu sorularında yalnız aşağıdaki gerçek runtime bağlamını kullan; tahmin etme.",
                "Verilen runtime bağlamını authoritative (tek güvenilir kaynak) kabul et.",
                "Runtime bağlamında bulunmayan bir subsystem'i aktif veya sağlıklı ilan etme; değeri yoksa 'bilinmiyor' de.",
                "Gerçek runtime bağlamı: " + json.dumps(runtime_context, ensure_ascii=False, sort_keys=True),
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
        output = self.last_route.output
        if self._requests_runtime_facts(message) and runtime_context and self.last_route.success:
            return self._ground_runtime_response(output, runtime_context)
        return output
