import threading
import time

import requests

from src.config.settings import Settings
from src.providers.base_provider import BaseProvider

# Sprint 40 (LOCAL RESOURCE CONTROL): birden fazla departman (research/
# finance/media, bkz. Sprint 39 canlı testi) AYNI ANDA Ollama'ya istek
# gönderdiğinde -- her Manager kendi ``ProviderManager()``/``OllamaProvider()``
# örneğini kurduğu için -- tek bir yerel çıkarım kaynağı (tek Ollama süreci)
# eşzamanlı yükleniyor ve 150 sn'lik görev zaman aşımı gerçek ve tekrarlanabilir
# şekilde aşılıyordu (Sprint 39 canlı test kanıtı). En küçük güvenli çözüm:
# MODÜL SEVİYESİNDE (tüm ``OllamaProvider`` örnekleri arasında PAYLAŞILAN,
# süreç genelinde TEK) bir semafor -- yalnızca gerçek HTTP çağrısını
# SIRALAR. Browser/GitHub gibi Ollama'ya hiç dokunmayan işler bundan
# ETKİLENMEZ (paralel kalır); global sistem serial hale GETİRİLMEZ.
#
# Sprint 41 düzeltmesi: ``PlanExecutor.run()``'ı satır satır okuyunca
# (bkz. Sprint 41 analizi) department task'larının aslında SIRALI (bloklayan
# ``future.result()``) çalıştığı, HİÇBİR ZAMAN gerçekten eşzamanlı Ollama
# isteği göndermediği doğrulandı -- Sprint 40'ın "eşzamanlı çakışma" teşhisi
# YANLIŞTI. Gerçek kök neden: bu semafor DEĞİL, aşağıdaki ``OLLAMA_REQUEST_
# TIMEOUT_SECONDS``'ın ``DEPARTMENT_TASK_TIMEOUT_SECONDS`` (150 sn,
# department_orchestrator.py) ile BİREBİR AYNI olmasıydı -- iki timeout
# yarışıyordu, dış (JobManager) timeout önce ateşlenirse arka plan iş
# parçacığı ÖLDÜRÜLEMEDEN çalışmaya devam ediyordu. Semafor YİNE DE
# korunuyor (gelecekte gerçek eşzamanlı Mission'lar -- ör. research_loop
# -- için savunma katmanı) ve artık ``queue_wait_seconds``/
# ``inference_seconds`` AYRI ölçülüyor (bkz. ``generate()``).
_OLLAMA_CONCURRENCY_LIMIT = 1
_OLLAMA_REQUEST_LOCK = threading.Semaphore(_OLLAMA_CONCURRENCY_LIMIT)

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

# Sprint 41: KASITLI OLARAK ``DEPARTMENT_TASK_TIMEOUT_SECONDS``'tan (150 sn,
# department_orchestrator.py) KÜÇÜK -- iç (HTTP) timeout, dış (JobManager
# görev) timeout'undan ÖNCE, temiz bir şekilde ateşlensin diye. Bu sayede
# JobManager'ın "arka plan iş parçacığı zorla durdurulamaz" kısıtı (bkz.
# job_manager.py) pratikte hiç devreye girmez -- Ollama çağrısı HER ZAMAN
# kendi kontrollü hata mesajıyla (``"Ollama zaman aşımına uğradı."``) önce
# döner. ``DEPARTMENT_TASK_TIMEOUT_SECONDS`` KASITLI OLARAK değiştirilmedi
# (github/browser/evaluation gibi Ollama'ya hiç dokunmayan departmanları
# etkilememesi için).
OLLAMA_REQUEST_TIMEOUT_SECONDS = 30


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
        # Sprint 41 (QUEUE WAIT vs INFERENCE TIME): son ``generate()``
        # çağrısının zamanlama dökümü -- ``ProviderManager.route_and_generate``
        # bunu (varsa, duck-typing ile) okuyup ``execution_history``'e
        # taşır. Diğer provider'larda bu öznitelik YOKTUR -- geriye dönük
        # uyumluluk ``getattr(..., None)`` ile korunur.
        self.last_call_timing: dict[str, float] | None = None

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

        # Sprint 41 (QUEUE WAIT vs INFERENCE TIME): semaforun kendisi
        # yalnızca gerçek HTTP isteğini sıralıyor (Sprint 40) -- burada
        # AYRICA, semafor BEKLEME süresi ile gerçek çıkarım süresi AYRI
        # ölçülüyor, böylece bir görev "yavaş" mı yoksa "sırada bekledi"
        # mi net şekilde ayırt edilebiliyor.
        # Sprint 44 fix: an unbounded ``.acquire()`` here meant a task that
        # already timed out at the JobManager/DEPARTMENT_TASK_TIMEOUT_SECONDS
        # level (its thread orphaned -- Python cannot kill it, see
        # job_manager.py) could still be holding this process-wide semaphore
        # indefinitely; a fresh call from the NEXT department/mission would
        # then block here with no timeout of its own, silently starving the
        # whole mission far past its own reported timeout (live-observed:
        # mission/worker stuck WORKING with no error). Bounding the wait to
        # the same margin as the HTTP call keeps the queue truthful and
        # finite instead of hanging behind an uncancellable orphan.
        queue_wait_started = time.monotonic()
        acquired = _OLLAMA_REQUEST_LOCK.acquire(timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS)
        queue_wait_seconds = round(time.monotonic() - queue_wait_started, 2)
        inference_seconds = 0.0

        if not acquired:
            self.last_call_timing = {"queue_wait_seconds": queue_wait_seconds, "inference_seconds": 0.0}
            return "Ollama meşgul: önceki çağrı serbest bırakılmadan kilit zaman aşımına uğradı."

        try:
            inference_started = time.monotonic()
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

            finally:
                inference_seconds = round(time.monotonic() - inference_started, 2)
        finally:
            if acquired:
                _OLLAMA_REQUEST_LOCK.release()
            self.last_call_timing = {
                "queue_wait_seconds": queue_wait_seconds,
                "inference_seconds": inference_seconds,
            }

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
