from __future__ import annotations

import threading
import time

import src.providers.ollama_provider as ollama_provider_module
from src.providers.ollama_provider import OllamaProvider


class _FakeResponse:
    status_code = 200

    def json(self):
        return {"message": {"content": "cevap"}}


class TestOllamaLockAcquireIsBounded:
    """Sprint 44: a department task that already timed out at the
    JobManager/DEPARTMENT_TASK_TIMEOUT_SECONDS level leaves its background
    thread orphaned -- Python cannot kill it (see job_manager.py). Before
    this fix, ``_OLLAMA_REQUEST_LOCK.acquire()`` had no timeout, so a fresh
    call from the NEXT department/mission could block behind that orphan
    for as long as its real (uncancellable) HTTP call took -- unbounded from
    the new caller's perspective, even though JobManager believed the
    department had a 75s ceiling. This is the live-observed "mission/worker
    stuck WORKING, no error, no log" signature reproduced at the provider
    layer: the lock wait must fail closed within a bounded time instead of
    blocking forever."""

    def test_generate_fails_closed_instead_of_blocking_forever_when_lock_is_held(self, monkeypatch):
        # Shrink the acquire-timeout so the test is fast without weakening
        # what it proves: an ORPHANED holder that never releases in time.
        monkeypatch.setattr(ollama_provider_module, "OLLAMA_REQUEST_TIMEOUT_SECONDS", 0.05)

        def slow_post(url, json=None, timeout=None):
            time.sleep(0.5)  # simulates a real call the holder can't be forced to cancel
            return _FakeResponse()

        monkeypatch.setattr(ollama_provider_module.requests, "post", slow_post)

        holder = OllamaProvider()
        holder_thread = threading.Thread(target=lambda: holder.generate("orphaned"), daemon=True)
        holder_thread.start()
        time.sleep(0.02)  # ensure the holder acquires the semaphore first

        waiter = OllamaProvider()
        started = time.monotonic()
        result = waiter.generate("fresh call queued behind the orphan")
        elapsed = time.monotonic() - started

        # Bounded: must return well before the orphan's 0.5s call finishes,
        # not silently wait for it.
        assert elapsed < 0.3
        assert "zaman aşımına uğradı" in result.casefold() or "meşgul" in result.casefold()

        holder_thread.join(timeout=5)

    def test_lock_timeout_message_is_treated_as_a_generation_failure(self, monkeypatch):
        # The message this fix returns must be recognized by the existing
        # failure-detection contract (provider_manager._is_generation_failure)
        # so route_and_generate() falls back to the next candidate provider
        # exactly like a real HTTP timeout does -- no new failure semantics.
        from src.providers.provider_manager import _is_generation_failure

        monkeypatch.setattr(ollama_provider_module, "OLLAMA_REQUEST_TIMEOUT_SECONDS", 0.05)

        def slow_post(url, json=None, timeout=None):
            time.sleep(0.5)
            return _FakeResponse()

        monkeypatch.setattr(ollama_provider_module.requests, "post", slow_post)

        holder = OllamaProvider()
        holder_thread = threading.Thread(target=lambda: holder.generate("orphaned"), daemon=True)
        holder_thread.start()
        time.sleep(0.02)

        result = OllamaProvider().generate("fresh call queued behind the orphan")
        assert _is_generation_failure(result) is True

        holder_thread.join(timeout=5)
