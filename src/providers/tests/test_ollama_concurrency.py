from __future__ import annotations

import threading
import time

import src.providers.ollama_provider as ollama_provider_module
from src.providers.ollama_provider import OllamaProvider


class _FakeResponse:
    status_code = 200

    def json(self):
        return {"message": {"content": "cevap"}}


class TestOllamaConcurrencyLock:
    """Sprint 40 (LOCAL RESOURCE CONTROL): birden fazla ``OllamaProvider``
    örneği (her Manager kendi örneğini kurar, bkz. Sprint 39 canlı test
    kanıtı) AYNI ANDA gerçek HTTP isteği göndermemeli -- modül seviyeli
    semafor bunu SIRALAMALI."""

    def test_two_concurrent_calls_do_not_overlap(self, monkeypatch):
        overlap_detected = {"value": False}
        active_calls = {"count": 0}
        lock = threading.Lock()

        def fake_post(url, json=None, timeout=None):
            with lock:
                active_calls["count"] += 1
                if active_calls["count"] > 1:
                    overlap_detected["value"] = True
            time.sleep(0.05)
            with lock:
                active_calls["count"] -= 1
            return _FakeResponse()

        monkeypatch.setattr(ollama_provider_module.requests, "post", fake_post)

        provider_a = OllamaProvider()
        provider_b = OllamaProvider()  # ayrı örnek -- modül seviyeli kilit paylaşılmalı

        results = []
        threads = [
            threading.Thread(target=lambda: results.append(provider_a.generate("a"))),
            threading.Thread(target=lambda: results.append(provider_b.generate("b"))),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert overlap_detected["value"] is False
        assert results == ["cevap", "cevap"]

    def test_health_check_is_not_blocked_by_a_held_generate_lock(self, monkeypatch):
        # Semafor yalnızca gerçek ÜRETİM (generate/HTTP POST) çağrısını
        # sıralamalı -- ``is_available()`` (ayrı bir GET, kilidi hiç
        # KULLANMAZ) bir generate() çağrısı devam ederken bile BLOKE
        # OLMAMALI.
        def slow_post(url, json=None, timeout=None):
            time.sleep(0.2)
            return _FakeResponse()

        def fast_get(url, timeout=None):
            return _FakeResponse()

        monkeypatch.setattr(ollama_provider_module.requests, "post", slow_post)
        monkeypatch.setattr(ollama_provider_module.requests, "get", fast_get)

        provider = OllamaProvider()
        holder_thread = threading.Thread(target=lambda: provider.generate("slow"))
        holder_thread.start()
        time.sleep(0.02)  # holder'ın kilidi almasını garanti et

        started = time.monotonic()
        available = OllamaProvider().is_available()
        elapsed = time.monotonic() - started

        holder_thread.join(timeout=5)

        assert available is True
        assert elapsed < 0.1  # semafor tarafından hiç BEKLETİLMEDİ


class TestSprint41QueueWaitVsInferenceTime:
    """Sprint 41 TEST A/B: 3 eşzamanlı Ollama çağrısında ne çakışma
    OLMALI ne de kuyruk bekleme süresi YOK SAYILMALI; Ollama'ya hiç
    dokunmayan bağımsız bir iş bundan ETKİLENMEMELİ."""

    def test_three_concurrent_calls_no_overlap_and_queue_wait_is_measurable(self, monkeypatch):
        overlap_detected = {"value": False}
        active_calls = {"count": 0}
        lock = threading.Lock()

        def fake_post(url, json=None, timeout=None):
            with lock:
                active_calls["count"] += 1
                if active_calls["count"] > 1:
                    overlap_detected["value"] = True
            time.sleep(0.08)
            with lock:
                active_calls["count"] -= 1
            return _FakeResponse()

        monkeypatch.setattr(ollama_provider_module.requests, "post", fake_post)

        providers = [OllamaProvider() for _ in range(3)]
        results = [None, None, None]

        def worker(index):
            results[index] = providers[index].generate(f"prompt-{index}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert overlap_detected["value"] is False
        assert results == ["cevap", "cevap", "cevap"]

        # Üçü de aynı anda başladığı için en az biri GERÇEKTEN sırada
        # bekledi -- yani queue_wait_seconds ÖLÇÜLEBİLİR (0'dan büyük).
        queue_waits = [p.last_call_timing["queue_wait_seconds"] for p in providers]
        assert max(queue_waits) > 0
        # Hiçbir görev "sırada beklediği için" yanlış timeout almadı --
        # üçü de başarıyla "cevap" döndürdü (yukarıda doğrulandı).

    def test_waiting_task_never_reports_a_false_timeout(self, monkeypatch):
        # Sırada bekleyen bir görev, gerçek çıkarım süresi kısa olsa bile
        # kuyruk bekleme süresiyle birlikte YANLIŞ bir "zaman aşımı"
        # SONUCU dönmemeli -- yalnızca GERÇEK HTTP timeout'u (bkz.
        # OLLAMA_REQUEST_TIMEOUT_SECONDS) bir hata üretmeli.
        def fast_post(url, json=None, timeout=None):
            time.sleep(0.05)
            return _FakeResponse()

        monkeypatch.setattr(ollama_provider_module.requests, "post", fast_post)

        holder = OllamaProvider()
        waiter = OllamaProvider()

        holder_thread = threading.Thread(target=lambda: holder.generate("a"))
        holder_thread.start()
        time.sleep(0.005)

        result = waiter.generate("b")
        holder_thread.join(timeout=5)

        assert result == "cevap"  # kuyrukta bekledi ama BAŞARILI oldu
        assert "zaman aşımına uğradı" not in result.casefold()


class TestOllamaLockDoesNotAffectOtherProviders:
    """Sprint 41 TEST B: Ollama kuyruğu, Ollama'ya hiç dokunmayan bağımsız
    işleri (browser/GitHub'ın kullandığı gerçek provider'lar dahil)
    ETKİLEMEMELİ."""

    def test_other_provider_call_proceeds_while_ollama_lock_is_held(self, monkeypatch):
        from src.providers.aiml_provider import AIMLProvider

        def slow_post(url, json=None, timeout=None):
            time.sleep(0.2)
            return _FakeResponse()

        monkeypatch.setattr(ollama_provider_module.requests, "post", slow_post)

        holder = OllamaProvider()
        holder_thread = threading.Thread(target=lambda: holder.generate("slow"))
        holder_thread.start()
        time.sleep(0.02)

        aiml = AIMLProvider()
        # AIML'in KENDİ ağ çağrısını mocklamaya gerek yok -- yalnızca
        # Ollama kilidine hiç DOKUNMADIĞINI (is_available üzerinden,
        # gerçek ağ hatası olsa bile hemen dönmesi gerektiğini) doğruluyoruz.
        started = time.monotonic()
        aiml.is_available()
        elapsed = time.monotonic() - started

        holder_thread.join(timeout=5)

        assert elapsed < 0.15  # Ollama kilidi tarafından hiç BEKLETİLMEDİ
