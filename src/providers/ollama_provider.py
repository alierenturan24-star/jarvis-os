import requests

from src.config.settings import Settings
from src.providers.base_provider import BaseProvider

# Sprint 19 (Beta Stabilization) düzeltmesi: önceden ``ollama run <model>
# <prompt>`` alt-süreci (subprocess CLI, "ham tamamlama" modu) kullanılıyordu.
# Ölçüldü (bkz. Sprint 19 raporu): tek bir çağrı 45-100+ saniye sürüyordu --
# bu hem department task timeout'unu (45 sn) DÜZENLİ olarak aşıyordu hem de
# (sistem bağlamı + kullanıcı mesajı tek bir düz metinde birleşince) küçük
# modelin kullanıcıya cevap vermek yerine sistem bağlamını olduğu gibi geri
# döktüğü davranışın kök nedeniydi. Zaten ÇALIŞAN Ollama sunucusunun (``ollama
# serve``) yerel HTTP sohbet API'sine geçmek hem ölçülebilir şekilde daha
# hızlı hem de -- ``system``/``user`` rollerini AYRI göndererek -- modelin
# bağlamı kopyalamak yerine gerçekten cevap vermesini sağlıyor. Yeni bir
# Provider/AI İCAT EDİLMEDİ; aynı ``OllamaProvider``, aynı yerel Ollama
# kurulumu, yalnızca iletişim yöntemi (CLI alt-süreci -> HTTP API) düzeltildi.
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
OLLAMA_REQUEST_TIMEOUT_SECONDS = 150


class OllamaProvider(BaseProvider):

    ERROR_MESSAGES = (
        "ollama bulunamadı",
        "zaman aşımına uğradı",
        "ollama hata verdi",
        "ollama hatası",
        "model cevap üretmedi",
    )

    def __init__(self) -> None:
        super().__init__("ollama")

    def is_available(self) -> bool:

        try:
            response = requests.get(OLLAMA_TAGS_URL, timeout=3)
            return response.status_code == 200
        except Exception:
            return False

    def health(self) -> dict:

        available = self.is_available()

        return {
            "provider": "ollama",
            "available": available,
            "local": True,
            "message": (
                "Ollama kullanılabilir."
                if available
                else "Ollama kullanılamıyor."
            ),
        }

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
    ) -> str:
        """``prompt`` (kullanıcı mesajı) ve isteğe bağlı ``system`` (JARVIS
        kimliği/proje bağlamı gibi sistem talimatları) AYRI roller olarak
        gönderilir. ``system`` verilmezse (mevcut çağıranların -- Research/
        Finance/Evolution -- davranışı DEĞİŞMEZ) tek bir ``user`` mesajı
        gönderilir, tıpkı öncekindeki gibi."""

        prompt = str(prompt).strip()

        if not prompt:
            return "Ollama için gönderilen istem boş."

        model = model or Settings.MODEL

        messages = []
        if system and system.strip():
            messages.append({"role": "system", "content": system.strip()})
        messages.append({"role": "user", "content": prompt})

        try:
            response = requests.post(
                OLLAMA_CHAT_URL,
                json={"model": model, "messages": messages, "stream": False},
                timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS,
            )

        except requests.exceptions.ConnectionError:
            return "Ollama bulunamadı."

        except requests.exceptions.Timeout:
            return "Ollama zaman aşımına uğradı."

        except Exception as error:
            return f"Ollama hatası: {error}"

        if response.status_code != 200:
            detail = response.text.strip() or "Bilinmeyen hata"
            return f"Ollama hata verdi: {detail}"

        try:
            data = response.json()
        except ValueError:
            return "Ollama hata verdi: geçersiz yanıt gövdesi."

        content = str((data.get("message") or {}).get("content", "")).strip()

        if not content:
            return "Model cevap üretmedi."

        return content

    def is_error_response(self, response: str) -> bool:

        text = str(response).casefold()

        return any(
            message in text
            for message in self.ERROR_MESSAGES
        )