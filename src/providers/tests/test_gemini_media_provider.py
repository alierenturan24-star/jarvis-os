from __future__ import annotations

import base64

import requests

from src.config.settings import Settings
from src.media.capability_model import TEXT_TO_IMAGE
from src.providers.gemini_media_provider import GeminiImageProvider


def test_gemini_image_provider_is_registered_only_in_media_registry():
    from src.media.provider_selection import _PROVIDERS
    from src.providers.provider_manager import ProviderManager

    ids = {provider.provider_id for provider in _PROVIDERS}
    assert "gemini_image" in ids
    assert "gemini_image" not in ProviderManager().names()


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(Settings, "GEMINI_API_KEY", "")
    provider = GeminiImageProvider()

    assert provider.is_available() is False
    assert provider.profiles()[0].availability is False
    result = provider.generate_image("original vertical news illustration")
    assert result.success is False
    assert "not configured" in result.error


def test_profile_is_paid_so_existing_approval_gate_applies(monkeypatch):
    monkeypatch.setattr(Settings, "GEMINI_API_KEY", "test-key-not-real")
    profile = GeminiImageProvider().profiles()[0]

    assert profile.cost_class == "paid"
    assert profile.free_tier is False
    assert TEXT_TO_IMAGE in profile.capabilities


def test_successful_generation_returns_inline_image_bytes(monkeypatch):
    encoded = base64.b64encode(b"real-gemini-image-bytes").decode()
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{
                "inlineData": {"mimeType": "image/png", "data": encoded}
            }]}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return _Response()

    monkeypatch.setattr(Settings, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.gemini_media_provider.requests.post", fake_post)
    result = GeminiImageProvider().generate_image("original scene", width=1080, height=1920)

    assert result.success is True
    assert result.content_bytes == b"real-gemini-image-bytes"
    assert result.provider_id == "gemini_image"
    assert result.model_id == Settings.GEMINI_IMAGE_MODEL
    assert captured["headers"]["x-goog-api-key"] == "test-key-not-real"
    assert "test-key-not-real" not in captured["url"]
    assert captured["json"]["generationConfig"] == {
        "responseModalities": ["IMAGE"],
        "imageConfig": {"aspectRatio": "9:16"},
    }


def test_auth_failure_is_truthful_and_does_not_leak_key(monkeypatch):
    secret = "super-secret-gemini-key"
    monkeypatch.setattr(Settings, "GEMINI_API_KEY", secret)

    def fake_post(*args, **kwargs):
        response = requests.Response()
        response.status_code = 401
        raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr("src.providers.gemini_media_provider.requests.post", fake_post)
    result = GeminiImageProvider().generate_image("anything")

    assert result.success is False
    assert "auth failed" in result.error.casefold()
    assert secret not in result.error
