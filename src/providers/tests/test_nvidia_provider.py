from __future__ import annotations

import base64

import pytest
import requests

from src.config.settings import Settings
from src.media.capability_model import TEXT_TO_IMAGE
from src.providers.nvidia_provider import NvidiaMediaProvider


# C: unauthenticated NVIDIA is unavailable, not crashed.
def test_unauthenticated_nvidia_is_unavailable_not_crashed(monkeypatch):
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "")
    provider = NvidiaMediaProvider()

    assert provider.is_available() is False
    assert "not configured" in provider.unavailable_reason()
    profile = provider.profiles()[0]
    assert profile.availability is False
    assert TEXT_TO_IMAGE in profile.capabilities

    result = provider.generate_image("a red bicycle")
    assert result.success is False
    assert "not configured" in result.error


def test_configured_nvidia_is_available_with_truthful_profile(monkeypatch):
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")
    provider = NvidiaMediaProvider()

    assert provider.is_available() is True
    assert provider.unavailable_reason() == ""
    profile = provider.profiles()[0]
    assert profile.availability is True
    assert profile.auth_required is True
    assert profile.local_or_remote == "remote"


def test_successful_generation_decodes_base64_image(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"artifacts": [{"base64": base64.b64encode(b"fake-image-bytes").decode(),
                                    "finishReason": "SUCCESS", "seed": 42}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _Response()

    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.nvidia_provider.requests.post", fake_post)
    provider = NvidiaMediaProvider()

    result = provider.generate_image("a swiss mountain village at sunrise", width=1080, height=1920)

    assert result.success is True
    assert result.content_bytes == b"fake-image-bytes"
    assert result.seed_used == 42
    assert captured["headers"]["Authorization"] == "Bearer test-key-not-real"
    assert "black-forest-labs/flux.1-schnell" in captured["url"]


# D: NVIDIA secret never appears in logs/status/errors.
def test_secret_never_appears_in_errors_or_profiles(monkeypatch):
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "super-secret-value-123")

    def fake_post(url, headers=None, json=None, timeout=None):
        response = requests.Response()
        response.status_code = 401
        raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr("src.providers.nvidia_provider.requests.post", fake_post)
    provider = NvidiaMediaProvider()

    result = provider.generate_image("anything")
    profile = provider.profiles()[0]

    assert "super-secret-value-123" not in result.error
    assert "super-secret-value-123" not in str(profile)
    assert "auth failed" in result.error.casefold()


def test_quota_error_is_reported_truthfully(monkeypatch):
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")

    def fake_post(url, headers=None, json=None, timeout=None):
        response = requests.Response()
        response.status_code = 429
        raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr("src.providers.nvidia_provider.requests.post", fake_post)
    provider = NvidiaMediaProvider()

    result = provider.generate_image("anything")

    assert result.success is False
    assert "quota" in result.error.casefold() or "rate limit" in result.error.casefold()


# Real request contract, verified 2026-08-26 against build.nvidia.com's own
# published code sample and its FLUX.1-schnell OpenAPI spec (ImageRequest/
# ImageResponse): invoke_url == f"{NVIDIA_BASE_URL}/{model_id}", payload
# fields prompt/width/height/seed/steps/samples/mode/cfg_scale, response
# artifacts[0].{base64,finishReason,seed}. This test pins that contract so a
# future accidental change (e.g. renaming a field) is caught without a live call.
def test_request_matches_official_flux_schnell_contract(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"artifacts": [{"base64": base64.b64encode(b"x").decode(),
                                    "finishReason": "SUCCESS", "seed": 7}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _Response()

    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.nvidia_provider.requests.post", fake_post)
    provider = NvidiaMediaProvider()

    provider.generate_image("swiss alps", width=768, height=1344, seed=42)

    assert captured["url"] == f"{Settings.NVIDIA_BASE_URL}/black-forest-labs/flux.1-schnell"
    assert captured["json"] == {
        "prompt": "swiss alps", "width": 768, "height": 1344, "seed": 42,
        "steps": 4, "samples": 1, "mode": "base", "cfg_scale": 0,
    }


# E: an HTTP error's JSON body detail is safe, useful diagnostic info that
# must survive into result.error -- prior behavior discarded it entirely.
def test_http_error_json_detail_is_preserved_safely(monkeypatch):
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")

    def fake_post(url, headers=None, json=None, timeout=None):
        response = requests.Response()
        response.status_code = 403
        response._content = b'{"detail": "model access not granted for this API key"}'
        raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr("src.providers.nvidia_provider.requests.post", fake_post)
    provider = NvidiaMediaProvider()

    result = provider.generate_image("anything")

    assert result.success is False
    assert "model access not granted for this API key" in result.error
    assert "test-key-not-real" not in result.error


# E: a non-JSON HTTP error body (e.g. an HTML gateway error page) still
# yields a truncated, safe text excerpt instead of being silently dropped.
def test_http_error_non_json_body_yields_truncated_text_excerpt(monkeypatch):
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")

    def fake_post(url, headers=None, json=None, timeout=None):
        response = requests.Response()
        response.status_code = 502
        response._content = b"<html>Bad Gateway</html>" + b"x" * 500
        raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr("src.providers.nvidia_provider.requests.post", fake_post)
    provider = NvidiaMediaProvider()

    result = provider.generate_image("anything")

    assert result.success is False
    assert "Bad Gateway" in result.error
    assert len(result.error) < 300


# 2026-08-26 live smoke test: a real hosted flux.1-schnell call exceeded the
# old flat 60s timeout. Fixed with a bounded (connect, read) tuple -- these
# tests pin that the configured values actually reach requests.post, and
# that a real ReadTimeout is reported truthfully, once, without leaking the key.

def test_configured_connect_and_read_timeouts_reach_requests_post(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"artifacts": [{"base64": base64.b64encode(b"x").decode(),
                                    "finishReason": "SUCCESS", "seed": 1}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(Settings, "NVIDIA_CONNECT_TIMEOUT_SECONDS", 7.5)
    monkeypatch.setattr(Settings, "NVIDIA_READ_TIMEOUT_SECONDS", 150.0)
    monkeypatch.setattr("src.providers.nvidia_provider.requests.post", fake_post)
    provider = NvidiaMediaProvider()

    provider.generate_image("anything")

    assert captured["timeout"] == (7.5, 150.0)


def test_read_timeout_is_reported_as_failure_not_crash(monkeypatch):
    call_count = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        call_count["n"] += 1
        raise requests.exceptions.ReadTimeout(
            f"HTTPSConnectionPool(host='ai.api.nvidia.com', port=443): Read timed out. (read timeout={timeout})"
        )

    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "super-secret-value-123")
    monkeypatch.setattr("src.providers.nvidia_provider.requests.post", fake_post)
    provider = NvidiaMediaProvider()

    result = provider.generate_image("anything")

    assert result.success is False
    assert result.content_bytes is None
    assert "timed out" in result.error.casefold()
    assert "read" in result.error.casefold()


def test_read_timeout_does_not_retry(monkeypatch):
    call_count = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        call_count["n"] += 1
        raise requests.exceptions.ReadTimeout("Read timed out.")

    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.nvidia_provider.requests.post", fake_post)
    provider = NvidiaMediaProvider()

    provider.generate_image("anything")

    assert call_count["n"] == 1


def test_timeout_error_never_leaks_key_or_authorization_header(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        raise requests.exceptions.ReadTimeout("Read timed out.")

    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "super-secret-value-123")
    monkeypatch.setattr("src.providers.nvidia_provider.requests.post", fake_post)
    provider = NvidiaMediaProvider()

    result = provider.generate_image("anything")

    assert "super-secret-value-123" not in result.error
    assert "Authorization" not in result.error
    assert "Bearer" not in result.error


def test_connect_timeout_is_distinguished_from_read_timeout(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        raise requests.exceptions.ConnectTimeout("Connection timed out.")

    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.nvidia_provider.requests.post", fake_post)
    provider = NvidiaMediaProvider()

    result = provider.generate_image("anything")

    assert result.success is False
    assert "connect" in result.error.casefold()
