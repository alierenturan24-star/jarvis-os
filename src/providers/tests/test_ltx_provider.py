from __future__ import annotations

import requests

from src.config.settings import Settings
from src.media.capability_model import IMAGE_TO_VIDEO, TEXT_TO_VIDEO
from src.providers.ltx_provider import LTXMediaProvider


class _JsonResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _queue_router(*, submit: dict, statuses: list[dict], result: dict):
    """Builds fake_post/fake_get pair reproducing fal's real queue contract:
    POST submit -> {"request_id", "status_url", "response_url"}; GET
    status_url (repeatedly) -> one of ``statuses`` in order; GET
    response_url -> ``result``."""
    calls = {"post": 0, "status": 0, "result": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["post"] += 1
        return _JsonResponse(submit)

    status_iter = iter(statuses)

    def fake_get(url, headers=None, timeout=None):
        if url == submit["status_url"]:
            calls["status"] += 1
            return _JsonResponse(next(status_iter))
        if url == submit["response_url"]:
            calls["result"] += 1
            return _JsonResponse(result)
        # download URL (the final video CDN link) -- no Authorization header
        class _Download:
            content = b"fake-video-bytes"

            def raise_for_status(self):
                return None
        return _Download()

    return fake_post, fake_get, calls


_SUBMIT = {
    "request_id": "req-123",
    "status_url": "https://queue.fal.run/lightricks/ltx-2.5/text-to-video/fast/requests/req-123/status",
    "response_url": "https://queue.fal.run/lightricks/ltx-2.5/text-to-video/fast/requests/req-123",
}
_RESULT = {"video": {"url": "https://cdn.fal.ai/fake/video.mp4", "content_type": "video/mp4"}}


# E: LTX local capability on unsupported hardware is unavailable truthfully.
def test_local_ltx_unavailable_on_hardware_without_gpu(monkeypatch):
    monkeypatch.setattr(LTXMediaProvider, "_gpu_detected", staticmethod(lambda: False))
    monkeypatch.setattr(Settings, "LTX_LOCAL_WEIGHTS_DIR", "")
    provider = LTXMediaProvider()

    assert provider.local_available() is False
    assert "no CUDA-capable GPU" in provider.local_unavailable_reason()
    local_profile = next(p for p in provider.profiles() if p.local_or_remote == "local")
    assert local_profile.availability is False
    assert "GPU" in local_profile.unavailable_reason


def test_local_ltx_still_unavailable_with_gpu_but_no_weights(monkeypatch):
    monkeypatch.setattr(LTXMediaProvider, "_gpu_detected", staticmethod(lambda: True))
    monkeypatch.setattr(Settings, "LTX_LOCAL_WEIGHTS_DIR", "")
    provider = LTXMediaProvider()

    assert provider.local_available() is False
    assert "weights" in provider.local_unavailable_reason()


def test_remote_ltx_unavailable_when_not_configured(monkeypatch):
    monkeypatch.setattr(Settings, "LTX_API_KEY", "")
    provider = LTXMediaProvider()

    assert provider.remote_available() is False
    assert provider.is_available() is False
    result = provider.generate_video_from_text("a bird flying over mountains")
    assert result.success is False
    assert "not configured" in result.error


# D: current official LTX-2.5 model ids are used (not the stale
# fal-ai/ltx-2/... ids), and profiles report text_to_video/image_to_video
# as two genuinely distinct model/profile entries.
def test_profiles_report_current_ltx_2_5_model_ids(monkeypatch):
    monkeypatch.setattr(Settings, "LTX_API_KEY", "test-key-not-real")
    provider = LTXMediaProvider()

    remote_profiles = [p for p in provider.profiles() if p.local_or_remote == "remote"]
    assert len(remote_profiles) == 2
    t2v = next(p for p in remote_profiles if p.capabilities == (TEXT_TO_VIDEO,))
    i2v = next(p for p in remote_profiles if p.capabilities == (IMAGE_TO_VIDEO,))
    assert t2v.model_id == "lightricks/ltx-2.5/text-to-video/fast"
    assert i2v.model_id == "lightricks/ltx-2.5/image-to-video/fast"
    assert "fal-ai/ltx-2/" not in t2v.model_id
    assert "fal-ai/ltx-2/" not in i2v.model_id


# E: text-to-video real queue flow -- submit -> status(IN_QUEUE/IN_PROGRESS)
# -> status(COMPLETED) -> result -> download.
def test_text_to_video_queue_flow_submits_polls_and_downloads(monkeypatch):
    fake_post, fake_get, calls = _queue_router(
        submit=_SUBMIT,
        statuses=[{"status": "IN_QUEUE"}, {"status": "IN_PROGRESS"}, {"status": "COMPLETED"}],
        result=_RESULT,
    )
    monkeypatch.setattr(Settings, "LTX_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.ltx_provider.requests.post", fake_post)
    monkeypatch.setattr("src.providers.ltx_provider.requests.get", fake_get)
    monkeypatch.setattr("src.providers.ltx_provider.time.sleep", lambda *_: None)
    provider = LTXMediaProvider()

    result = provider.generate_video_from_text("a bird flying over mountains", duration_seconds=6)

    assert result.success is True, result.error
    assert result.content_bytes == b"fake-video-bytes"
    assert result.content_url == "https://cdn.fal.ai/fake/video.mp4"
    assert calls["post"] == 1
    assert calls["status"] == 3
    assert calls["result"] == 1


# F: image-to-video real queue flow, verifying image_url reaches the submit body.
def test_image_to_video_queue_flow_submits_polls_and_downloads(monkeypatch):
    submit = {
        "request_id": "req-456",
        "status_url": "https://queue.fal.run/lightricks/ltx-2.5/image-to-video/fast/requests/req-456/status",
        "response_url": "https://queue.fal.run/lightricks/ltx-2.5/image-to-video/fast/requests/req-456",
    }
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _JsonResponse(submit)

    def fake_get(url, headers=None, timeout=None):
        if url == submit["status_url"]:
            return _JsonResponse({"status": "COMPLETED"})
        if url == submit["response_url"]:
            return _JsonResponse(_RESULT)
        class _Download:
            content = b"fake-video-bytes"

            def raise_for_status(self):
                return None
        return _Download()

    monkeypatch.setattr(Settings, "LTX_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.ltx_provider.requests.post", fake_post)
    monkeypatch.setattr("src.providers.ltx_provider.requests.get", fake_get)
    monkeypatch.setattr("src.providers.ltx_provider.time.sleep", lambda *_: None)
    provider = LTXMediaProvider()

    result = provider.generate_video_from_image("a running fox", "https://cdn.fal.ai/source/fox.png")

    assert result.success is True, result.error
    assert captured["json"]["image_url"] == "https://cdn.fal.ai/source/fox.png"
    assert captured["headers"]["Authorization"] == "Key test-key-not-real"
    assert "lightricks/ltx-2.5/image-to-video/fast" in captured["url"]


class _FakeClock:
    """Deterministic monotonic clock: returns 0, 1, 2, 3, ... on successive
    calls, so a bounded polling loop's deadline check is exercised without
    any real wall-clock waiting."""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        value = float(self.calls)
        self.calls += 1
        return value


# G: bounded polling timeout -- a request stuck IN_PROGRESS forever still
# terminates (never an infinite loop) once the configured deadline passes.
def test_bounded_polling_timeout_terminates_and_reports_truthfully(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _JsonResponse(_SUBMIT)

    status_calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        status_calls["n"] += 1
        return _JsonResponse({"status": "IN_PROGRESS"})

    monkeypatch.setattr(Settings, "LTX_API_KEY", "test-key-not-real")
    monkeypatch.setattr(Settings, "LTX_QUEUE_DEADLINE_SECONDS", 3.0)
    monkeypatch.setattr("src.providers.ltx_provider.requests.post", fake_post)
    monkeypatch.setattr("src.providers.ltx_provider.requests.get", fake_get)
    monkeypatch.setattr("src.providers.ltx_provider.time.sleep", lambda *_: None)
    monkeypatch.setattr("src.providers.ltx_provider.time.monotonic", _FakeClock())
    provider = LTXMediaProvider()

    result = provider.generate_video_from_text("anything")

    assert result.success is False
    assert result.content_bytes is None
    assert "timed out" in result.error.casefold()
    assert status_calls["n"] >= 1  # real polling happened, not an immediate give-up
    assert status_calls["n"] < 1000  # sanity: this really terminated, not an infinite loop


# H: a timed-out generation must NOT resubmit the same request -- exactly
# one POST (the initial submit) no matter how many status polls occurred.
def test_timeout_does_not_duplicate_submit(monkeypatch):
    post_calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        post_calls["n"] += 1
        return _JsonResponse(_SUBMIT)

    def fake_get(url, headers=None, timeout=None):
        return _JsonResponse({"status": "IN_PROGRESS"})

    monkeypatch.setattr(Settings, "LTX_API_KEY", "test-key-not-real")
    monkeypatch.setattr(Settings, "LTX_QUEUE_DEADLINE_SECONDS", 3.0)
    monkeypatch.setattr("src.providers.ltx_provider.requests.post", fake_post)
    monkeypatch.setattr("src.providers.ltx_provider.requests.get", fake_get)
    monkeypatch.setattr("src.providers.ltx_provider.time.sleep", lambda *_: None)
    monkeypatch.setattr("src.providers.ltx_provider.time.monotonic", _FakeClock())
    provider = LTXMediaProvider()

    provider.generate_video_from_text("anything")

    assert post_calls["n"] == 1


def test_secret_never_appears_in_errors(monkeypatch):
    monkeypatch.setattr(Settings, "LTX_API_KEY", "super-secret-ltx-key")

    def fake_post(url, headers=None, json=None, timeout=None):
        response = requests.Response()
        response.status_code = 401
        raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr("src.providers.ltx_provider.requests.post", fake_post)
    provider = LTXMediaProvider()

    result = provider.generate_video_from_text("anything")

    assert "super-secret-ltx-key" not in result.error
    assert "Authorization" not in result.error


def test_capabilities_include_text_and_image_to_video():
    provider = LTXMediaProvider()
    assert TEXT_TO_VIDEO in provider.capabilities()
    assert IMAGE_TO_VIDEO in provider.capabilities()
