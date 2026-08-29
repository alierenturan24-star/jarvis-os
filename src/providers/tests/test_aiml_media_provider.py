from __future__ import annotations

import base64

import pytest
import requests

from src.config.settings import Settings
from src.media.capability_model import TEXT_TO_IMAGE
from src.providers.aiml_media_provider import AIMLMediaProvider

# Mirrors src/providers/tests/test_nvidia_provider.py's structure/coverage
# for the same MediaProvider contract, applied to AIML API's own real
# documented image-generation endpoint (see aiml_media_provider.py's module
# docstring for the verified request/response contract and sources).


# 1: AIML appears as a text_to_image media provider, registered alongside
# the existing NVIDIA/fal/LTX providers.
def test_aiml_is_registered_as_a_text_to_image_media_provider():
    from src.media.provider_selection import _PROVIDERS

    ids = [provider.provider_id for provider in _PROVIDERS]
    assert "aiml" in ids
    assert {"nvidia", "fal", "ltx", "aiml"} <= set(ids)

    provider = next(p for p in _PROVIDERS if p.provider_id == "aiml")
    assert TEXT_TO_IMAGE in provider.capabilities()


# 2: missing AIML_API_KEY makes it unavailable, not crashed.
def test_missing_key_is_unavailable_not_crashed(monkeypatch):
    monkeypatch.setattr(Settings, "AIML_API_KEY", "")
    provider = AIMLMediaProvider()

    assert provider.is_available() is False
    assert "not configured" in provider.unavailable_reason()
    profile = provider.profiles()[0]
    assert profile.availability is False
    assert TEXT_TO_IMAGE in profile.capabilities

    result = provider.generate_image("a red bicycle")
    assert result.success is False
    assert "not configured" in result.error


def test_configured_key_is_available_with_truthful_profile(monkeypatch):
    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")
    provider = AIMLMediaProvider()

    assert provider.is_available() is True
    assert provider.unavailable_reason() == ""
    profile = provider.profiles()[0]
    assert profile.availability is True
    assert profile.auth_required is True
    assert profile.local_or_remote == "remote"
    assert profile.model_id == Settings.AIML_IMAGE_MODEL


# 3: the existing TEXT AIML provider (chat/completions) is completely
# unaffected -- separate class, separate model setting, separate registry.
def test_existing_text_aiml_provider_is_unaffected():
    from src.providers.aiml_provider import AIMLProvider
    from src.providers.provider_manager import ProviderManager

    assert Settings.AIML_DEFAULT_MODEL == "openai/gpt-4.1-mini"
    text_provider = AIMLProvider()
    assert hasattr(text_provider, "generate")
    assert not hasattr(text_provider, "generate_image")

    manager = ProviderManager()
    assert "aiml" in manager.names()  # the TEXT provider remains registered
    assert manager.get("aiml").__class__.__name__ == "AIMLProvider"


def test_media_aiml_provider_is_not_registered_in_provider_manager_text_chain():
    from src.providers.cost_optimizer import PLAN_CLI_PROVIDERS, TASK_COST_PROFILES
    from src.providers.provider_manager import ProviderManager, TASK_TYPE_PROVIDERS

    # "aiml" legitimately appears in TASK_TYPE_PROVIDERS/ProviderManager --
    # that is the pre-existing TEXT provider, unrelated to this round. What
    # must NOT happen: the media provider class itself never gets pulled
    # into the generic text-completion fallback chain (same separation
    # test_media_provider_isolation.py already proves for nvidia/fal/ltx).
    manager = ProviderManager()
    assert manager.get("aiml").__class__.__name__ != "AIMLMediaProvider"
    for profile in TASK_COST_PROFILES.values():
        assert profile.priority_provider != "aiml_media"
        assert profile.fallback_provider != "aiml_media"


# 4 + 5: successful mocked image response creates a real local image
# artifact/result, with truthful provenance (aiml + actual model +
# text_to_image).
def test_successful_generation_returns_real_bytes_with_correct_provenance(tmp_path, monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"images": [{"url": "https://cdn.aimlapi.com/eagle/files/x.png",
                                 "width": 1024, "height": 768, "content_type": "image/png"}],
                     "seed": 42, "has_nsfw_concepts": [False], "prompt": "swiss mountain village"}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["post_url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _Response()

    def fake_get(url, timeout=None):
        captured["download_url"] = url
        return type("R", (), {"raise_for_status": lambda self: None,
                               "content": b"real-png-bytes-not-fake-metadata"})()

    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.aiml_media_provider.requests.post", fake_post)
    monkeypatch.setattr("src.providers.aiml_media_provider.requests.get", fake_get)
    provider = AIMLMediaProvider()

    result = provider.generate_image("a swiss mountain village at sunrise", width=1080, height=1920)

    assert result.success is True
    assert result.content_bytes == b"real-png-bytes-not-fake-metadata"
    assert result.seed_used == 42
    assert captured["headers"]["Authorization"] == "Bearer test-key-not-real"

    # The bytes are a genuine, writable local artifact -- the SAME thing
    # GeneralProductionBuilder._generate_scene_image already does
    # provider-agnostically for nvidia/fal (path.write_bytes(...)).
    scene_file = tmp_path / "scene-01.png"
    scene_file.write_bytes(result.content_bytes)
    assert scene_file.read_bytes() == b"real-png-bytes-not-fake-metadata"

    # Provenance.
    assert result.provider_id == "aiml"
    assert result.model_id == Settings.AIML_IMAGE_MODEL
    assert result.capability == TEXT_TO_IMAGE


def test_request_matches_documented_flux_schnell_contract(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"images": [{"url": "https://cdn.aimlapi.com/x.png"}], "seed": 7}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _Response()

    def fake_get(url, timeout=None):
        return type("R", (), {"raise_for_status": lambda self: None, "content": b"x"})()

    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.aiml_media_provider.requests.post", fake_post)
    monkeypatch.setattr("src.providers.aiml_media_provider.requests.get", fake_get)
    provider = AIMLMediaProvider()

    provider.generate_image("swiss alps", width=1000, height=1900, seed=42)

    assert captured["url"] == f"{Settings.AIML_BASE_URL}/images/generations"
    assert captured["json"] == {
        "model": Settings.AIML_IMAGE_MODEL, "prompt": "swiss alps",
        # 1000 -> nearest multiple of 32 = 992; 1900 -> nearest multiple of
        # 32 is 1888, but AIML's documented max dimension is 1536.
        "image_size": {"width": 992, "height": 1536},
        "num_images": 1, "enable_safety_checker": True, "seed": 42,
    }
    assert captured["timeout"] == Settings.AIML_TIMEOUT


def test_b64_json_response_shape_is_also_handled(monkeypatch):
    # The SAME docs page shows a second, generic OpenAI-style envelope for
    # the same model -- handled defensively, never assumed.
    encoded = base64.b64encode(b"decoded-image-bytes").decode()

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": encoded}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        return _Response()

    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.aiml_media_provider.requests.post", fake_post)
    provider = AIMLMediaProvider()

    result = provider.generate_image("anything")

    assert result.success is True
    assert result.content_bytes == b"decoded-image-bytes"


# 6: authentication failure is truthful.
def test_authentication_failure_is_truthful(monkeypatch):
    monkeypatch.setattr(Settings, "AIML_API_KEY", "super-secret-value-123")

    def fake_post(url, headers=None, json=None, timeout=None):
        response = requests.Response()
        response.status_code = 401
        raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr("src.providers.aiml_media_provider.requests.post", fake_post)
    provider = AIMLMediaProvider()

    result = provider.generate_image("anything")

    assert result.success is False
    assert "auth failed" in result.error.casefold()
    assert "super-secret-value-123" not in result.error


# 7: quota/billing failure is truthful (AIML documents 403 as "authenticated
# but no credits" -- distinct from generic 401 auth failure -- and 429 as
# rate limiting).
def test_billing_quota_failure_is_truthful(monkeypatch):
    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")

    def fake_post(url, headers=None, json=None, timeout=None):
        response = requests.Response()
        response.status_code = 403
        raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr("src.providers.aiml_media_provider.requests.post", fake_post)
    provider = AIMLMediaProvider()

    result = provider.generate_image("anything")

    assert result.success is False
    assert "quota" in result.error.casefold() or "billing" in result.error.casefold() or "credits" in result.error.casefold()


def test_rate_limit_failure_is_truthful(monkeypatch):
    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")

    def fake_post(url, headers=None, json=None, timeout=None):
        response = requests.Response()
        response.status_code = 429
        raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr("src.providers.aiml_media_provider.requests.post", fake_post)
    provider = AIMLMediaProvider()

    result = provider.generate_image("anything")

    assert result.success is False
    assert "rate limit" in result.error.casefold()


# 8: timeout is bounded, uses the existing AIML_TIMEOUT setting, never retries.
def test_timeout_is_bounded_by_aiml_timeout_and_not_retried(monkeypatch):
    call_count = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        call_count["n"] += 1
        assert timeout == Settings.AIML_TIMEOUT
        raise requests.exceptions.Timeout("Read timed out.")

    monkeypatch.setattr(Settings, "AIML_API_KEY", "super-secret-value-123")
    monkeypatch.setattr("src.providers.aiml_media_provider.requests.post", fake_post)
    provider = AIMLMediaProvider()

    result = provider.generate_image("anything")

    assert result.success is False
    assert result.content_bytes is None
    assert "timed out" in result.error.casefold()
    assert str(Settings.AIML_TIMEOUT) in result.error
    assert call_count["n"] == 1  # no retry
    assert "super-secret-value-123" not in result.error


# 9: malformed responses fail safely (no crash, no fabricated artifact).
@pytest.mark.parametrize("body", [
    {},
    {"images": []},
    {"images": [None]},
    {"images": [{"width": 100}]},  # no url/b64_json
    {"data": [{}]},
])
def test_malformed_response_fails_safely(monkeypatch, body):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return body

    def fake_post(url, headers=None, json=None, timeout=None):
        return _Response()

    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.aiml_media_provider.requests.post", fake_post)
    provider = AIMLMediaProvider()

    result = provider.generate_image("anything")

    assert result.success is False
    assert result.content_bytes is None
    assert result.error


def test_invalid_json_body_fails_safely(monkeypatch):
    class _Response:
        text = "not-json-body"

        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.providers.aiml_media_provider.requests.post", lambda *a, **k: _Response())
    provider = AIMLMediaProvider()

    result = provider.generate_image("anything")

    assert result.success is False
    assert result.content_bytes is None


# 10: AIML participates in normal provider ranking (no special-casing as
# "always preferred").
def test_aiml_participates_in_normal_ranking(tmp_path, monkeypatch):
    from src.providers.execution_history import ProviderExecutionHistory
    from src.media.provider_selection import rank_available_providers

    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(Settings, "FAL_API_KEY", "test-key-not-real")
    monkeypatch.chdir(tmp_path)

    eligible, considered = rank_available_providers(TEXT_TO_IMAGE, history=ProviderExecutionHistory())
    ids = [profile.provider_id for profile, _ in eligible]

    assert "aiml" in ids
    assert {"nvidia", "fal", "aiml"} <= set(ids)
    # Cost class is truthfully "paid" -- ranking is left to the EXISTING,
    # unmodified _score() policy (free/local preferred over paid at equal
    # health), not hardcoded/forced here.
    aiml_profile = next(p for p, _ in eligible if p.provider_id == "aiml")
    assert aiml_profile.cost_class == "paid"


def test_no_providers_configured_produces_a_truthful_gap(tmp_path, monkeypatch):
    from src.media.provider_selection import select_media_provider

    monkeypatch.setattr(Settings, "AIML_API_KEY", "")
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "")
    monkeypatch.setattr(Settings, "FAL_API_KEY", "")
    monkeypatch.setattr(Settings, "LTX_API_KEY", "")
    monkeypatch.chdir(tmp_path)

    result = select_media_provider(TEXT_TO_IMAGE)
    assert result.gap is True
    assert result.selected is None


# 11: existing NVIDIA/fal/LTX registration/ordering is unaffected by adding AIML.
def test_existing_media_providers_unaffected_by_the_addition():
    from src.media.provider_selection import _PROVIDERS

    ids = [provider.provider_id for provider in _PROVIDERS]
    assert ids[:3] == ["nvidia", "fal", "ltx"]
    assert ids == ["nvidia", "fal", "ltx", "aiml"]


# 12: provider health/cooldown works through the SAME existing mechanism.
def test_provider_health_cooldown_applies_to_aiml_through_existing_mechanism(tmp_path, monkeypatch):
    from src.providers.execution_history import ProviderExecutionHistory
    from src.media.provider_selection import provider_health

    monkeypatch.chdir(tmp_path)
    history = ProviderExecutionHistory()
    for _ in range(3):
        history.record(task_type=TEXT_TO_IMAGE, provider="aiml", success=False,
                        fallback_used=False, duration_seconds=1.0, cost_class="paid")

    health = provider_health("aiml", TEXT_TO_IMAGE, history)
    assert health.status == "COOLDOWN"

    history.record(task_type=TEXT_TO_IMAGE, provider="aiml", success=True,
                    fallback_used=False, duration_seconds=1.0, cost_class="paid")
    health_after_success = provider_health("aiml", TEXT_TO_IMAGE, history)
    assert health_after_success.status == "HEALTHY"


# 13: secret never leaks anywhere (errors, profiles, string repr).
def test_secret_never_appears_in_errors_or_profiles(monkeypatch):
    monkeypatch.setattr(Settings, "AIML_API_KEY", "super-secret-value-123")

    def fake_post(url, headers=None, json=None, timeout=None):
        response = requests.Response()
        response.status_code = 401
        raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr("src.providers.aiml_media_provider.requests.post", fake_post)
    provider = AIMLMediaProvider()

    result = provider.generate_image("anything")
    profile = provider.profiles()[0]

    assert "super-secret-value-123" not in result.error
    assert "super-secret-value-123" not in str(profile)


# 14: YouTube publish approval-gating is unaffected by adding a new media
# provider (unchanged from prior rounds).
def test_youtube_publish_actions_remain_approval_gated():
    from src.security.action_policy import ActionPolicy

    assert "publish_scheduled_video" not in ActionPolicy.LOW_RISK_ACTIONS
    assert "upload_private_video" not in ActionPolicy.LOW_RISK_ACTIONS
