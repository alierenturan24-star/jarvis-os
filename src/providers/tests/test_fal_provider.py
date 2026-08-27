from __future__ import annotations

import requests

from src.config.settings import Settings
from src.media.capability_model import TEXT_TO_IMAGE
from src.providers.fal_provider import FalMediaProvider


# A: fal FLUX unavailable without a key (neither FAL_API_KEY nor the
# fal.ai-shared LTX_API_KEY configured).
def test_fal_unavailable_without_any_key(monkeypatch):
    monkeypatch.setattr(Settings, "FAL_API_KEY", "")
    monkeypatch.setattr(Settings, "LTX_API_KEY", "")
    provider = FalMediaProvider()

    assert provider.is_available() is False
    assert "not configured" in provider.unavailable_reason()
    profile = provider.profiles()[0]
    assert profile.availability is False

    result = provider.generate_image("a red bicycle")
    assert result.success is False
    assert "not configured" in result.error


# B: fal FLUX becomes available/configured via FAL_API_KEY without leaking it.
def test_fal_available_with_explicit_fal_key_without_leaking_it(monkeypatch):
    monkeypatch.setattr(Settings, "FAL_API_KEY", "super-secret-fal-key")
    monkeypatch.setattr(Settings, "LTX_API_KEY", "")
    provider = FalMediaProvider()

    assert provider.is_available() is True
    assert provider.unavailable_reason() == ""
    profile = provider.profiles()[0]
    assert profile.availability is True
    assert profile.auth_required is True
    assert "super-secret-fal-key" not in str(profile)


# B (continued): fal.ai issues one account-wide key -- the already-
# configured LTX_API_KEY (also a fal.ai key) unlocks fal FLUX too, with no
# second .env edit, and still never leaks.
def test_fal_available_via_shared_ltx_api_key_without_leaking_it(monkeypatch):
    monkeypatch.setattr(Settings, "FAL_API_KEY", "")
    monkeypatch.setattr(Settings, "LTX_API_KEY", "super-secret-ltx-key-reused-by-fal")
    provider = FalMediaProvider()

    assert provider.is_available() is True
    result_profile = provider.profiles()[0]
    assert "super-secret-ltx-key-reused-by-fal" not in str(result_profile)


# C: correct official FLUX schnell endpoint/payload/response parsing
# (verified 2026-08-26 against fal.ai's own docs).
def test_request_matches_official_flux_schnell_contract(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"images": [{"url": "https://v3.fal.media/files/rabbit/abc123.png",
                                 "width": 1024, "height": 1024, "content_type": "image/png"}],
                     "seed": 7, "has_nsfw_concepts": [False], "prompt": "swiss alps"}

    class _Download:
        content = b"fake-image-bytes"

        def raise_for_status(self):
            return None

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _Response()

    def fake_get(url, timeout=None):
        captured["download_url"] = url
        return _Download()

    monkeypatch.setattr(Settings, "FAL_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.fal_provider.requests.post", fake_post)
    monkeypatch.setattr("src.providers.fal_provider.requests.get", fake_get)
    provider = FalMediaProvider()

    result = provider.generate_image("swiss alps", width=1024, height=1024, seed=42)

    assert result.success is True, result.error
    assert result.content_bytes == b"fake-image-bytes"
    assert result.content_url == "https://v3.fal.media/files/rabbit/abc123.png"
    assert result.seed_used == 7
    assert captured["url"] == f"{Settings.FAL_BASE_URL}/fal-ai/flux/schnell"
    assert captured["headers"]["Authorization"] == "Key test-key-not-real"
    assert captured["json"]["prompt"] == "swiss alps"
    assert captured["json"]["image_size"] == {"width": 1024, "height": 1024}
    assert captured["json"]["seed"] == 42
    assert captured["download_url"] == "https://v3.fal.media/files/rabbit/abc123.png"


def test_zero_seed_omitted_from_payload_meaning_random(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"images": [{"url": "https://cdn.fal.ai/x.png"}], "seed": 999}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _Response()

    def fake_get(url, timeout=None):
        class _Download:
            content = b"x"

            def raise_for_status(self):
                return None
        return _Download()

    monkeypatch.setattr(Settings, "FAL_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.fal_provider.requests.post", fake_post)
    monkeypatch.setattr("src.providers.fal_provider.requests.get", fake_get)
    provider = FalMediaProvider()

    provider.generate_image("anything", seed=0)

    assert "seed" not in captured["json"]


# M: no secret leakage on HTTP error / timeout paths.
def test_secret_never_appears_in_http_error(monkeypatch):
    monkeypatch.setattr(Settings, "FAL_API_KEY", "super-secret-fal-key-value")

    def fake_post(url, headers=None, json=None, timeout=None):
        response = requests.Response()
        response.status_code = 401
        raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr("src.providers.fal_provider.requests.post", fake_post)
    provider = FalMediaProvider()

    result = provider.generate_image("anything")

    assert "super-secret-fal-key-value" not in result.error
    assert "auth failed" in result.error.casefold()


def test_read_timeout_is_reported_without_crash_or_retry(monkeypatch):
    call_count = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        call_count["n"] += 1
        raise requests.exceptions.ReadTimeout("Read timed out.")

    monkeypatch.setattr(Settings, "FAL_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.fal_provider.requests.post", fake_post)
    provider = FalMediaProvider()

    result = provider.generate_image("anything")

    assert result.success is False
    assert "timed out" in result.error.casefold()
    assert call_count["n"] == 1


def test_capabilities_only_claim_text_to_image():
    provider = FalMediaProvider()
    assert provider.capabilities() == (TEXT_TO_IMAGE,)
