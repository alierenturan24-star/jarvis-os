from __future__ import annotations

import pytest
import requests

from src.config.settings import Settings
from src.media.capability_model import IMAGE_TO_VIDEO, MediaGenerationResult, MediaModelProfile, TEXT_TO_IMAGE
from src.media.production import GeneralProductionBuilder, ScenePlan
from src.media.provider_selection import provider_health
from src.providers.aiml_media_provider import AIMLMediaProvider
from src.providers.execution_history import ProviderExecutionHistory
from src.providers.fal_provider import FalMediaProvider
from src.providers.ltx_provider import LTXMediaProvider
from src.providers.media_provider_base import MediaProvider
from src.providers.nvidia_provider import NvidiaMediaProvider

# Sprint: paid media provider approval safety fix. Inspection found NVIDIA/
# fal/LTX/AIML had NO approval gate before their real HTTP/API call --
# only capability/availability (API key present) was checked, never
# authorization to actually SPEND. These tests prove the ONE generic gate
# added in src.media.production (_paid_media_approval_decision, checked in
# _generate_scene_image/_maybe_generate_scene_motion) -- keyed purely off
# MediaModelProfile.cost_class, reusing the EXISTING ActionPolicy
# ("paid_media_generation" in MEDIUM_RISK_ACTIONS), no second approval
# system. Mocks only -- no real network/paid calls anywhere in this file.


def _scene() -> ScenePlan:
    return ScenePlan(scene_id="s1", script_beat_id="HOOK", purpose="hook",
                      narration_segment="narration", visual_description="a swiss mountain village at sunrise",
                      duration_seconds=8.0)


def _no_http(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("no real HTTP call should happen without approval")
    monkeypatch.setattr("requests.post", _boom)
    monkeypatch.setattr("requests.get", _boom)


# 1: paid AIML image generation without approval makes ZERO HTTP calls and
# returns approval required.
def test_unapproved_aiml_generation_makes_zero_http_calls_and_reports_approval_required(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")
    _no_http(monkeypatch)

    provider = AIMLMediaProvider()
    profile = provider.profiles()[0]
    assert profile.cost_class == "paid"

    image_path, entry = GeneralProductionBuilder._generate_scene_image(
        [(profile, provider)], _scene(), 1, tmp_path, standing_permission=False,
    )

    assert image_path is None
    assert entry.success is False
    assert entry.quality_evidence.get("approval_required") is True
    assert "aiml" in entry.quality_evidence["reason"]


# 2: approved AIML generation reaches the mocked provider call.
def test_approved_aiml_generation_reaches_the_mocked_provider_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")
    calls = {"n": 0}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"images": [{"url": "https://cdn.aimlapi.com/x.png"}], "seed": 1}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        return _Response()

    def fake_get(url, timeout=None):
        return type("R", (), {"raise_for_status": lambda self: None, "content": b"x" * 5000})()

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.get", fake_get)

    provider = AIMLMediaProvider()
    profile = provider.profiles()[0]

    image_path, entry = GeneralProductionBuilder._generate_scene_image(
        [(profile, provider)], _scene(), 1, tmp_path, standing_permission=True,
    )

    assert calls["n"] == 1  # the mocked provider call WAS reached
    assert image_path is not None
    assert entry.success is True
    assert entry.provider == "aiml"


# 3: NVIDIA/fal paid text_to_image paths are governed by the same generic rule.
@pytest.mark.parametrize("provider_cls,key_attr", [
    (NvidiaMediaProvider, "NVIDIA_API_KEY"),
    (FalMediaProvider, "FAL_API_KEY"),
])
def test_nvidia_and_fal_paid_paths_are_governed_by_the_same_rule(tmp_path, monkeypatch, provider_cls, key_attr):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, key_attr, "test-key-not-real")
    _no_http(monkeypatch)

    provider = provider_cls()
    profile = provider.profiles()[0]
    assert profile.cost_class == "paid"

    image_path, entry = GeneralProductionBuilder._generate_scene_image(
        [(profile, provider)], _scene(), 1, tmp_path, standing_permission=False,
    )

    assert image_path is None
    assert entry.quality_evidence.get("approval_required") is True


# 3 cont.: remote LTX's paid image_to_video (motion) path is governed by
# the same generic rule -- a different call site (_maybe_generate_scene_motion).
def test_remote_ltx_paid_motion_path_is_governed_by_the_same_rule(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "LTX_API_KEY", "test-key-not-real")
    _no_http(monkeypatch)

    provider = LTXMediaProvider()
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (provider,))
    # LTX also has a LOCAL image-to-video profile (unavailable in this test
    # environment, and correctly "free") -- select the REMOTE (paid) one.
    profile = next(p for p in provider.profiles()
                    if IMAGE_TO_VIDEO in p.capabilities and p.local_or_remote == "remote")
    assert profile.cost_class == "paid"

    history = ProviderExecutionHistory()
    motion_path, motion_entry = GeneralProductionBuilder._maybe_generate_scene_motion(
        _scene(), "https://cdn.fal.ai/fake/img.png", 1, tmp_path, history, standing_permission=False,
    )

    # Motion is a bonus enhancement -- an unapproved candidate is treated
    # exactly like any other unavailable one: silently skipped, no crash,
    # no build-blocking failure (the still image is kept by the caller).
    assert motion_path is None


# 4: local/free media remains unaffected -- never gated, never asks for approval.
def test_free_local_provider_is_never_gated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = {"n": 0}

    class _FreeProvider(MediaProvider):
        def __init__(self):
            super().__init__("free-fake")

        def capabilities(self):
            return (TEXT_TO_IMAGE,)

        def is_available(self):
            return True

        def unavailable_reason(self):
            return ""

        def profiles(self):
            return (MediaModelProfile(
                provider_id="free-fake", model_id="m", capabilities=(TEXT_TO_IMAGE,),
                availability=True, auth_required=False, cost_class="free", free_tier=True,
                subscription_cli=False, local_or_remote="local", quality_tier=50, speed_tier=50),)

        def generate_image(self, prompt, **kwargs):
            calls["n"] += 1
            return MediaGenerationResult(True, "free-fake", "m", TEXT_TO_IMAGE, content_bytes=b"x" * 5000)

    provider = _FreeProvider()
    profile = provider.profiles()[0]

    image_path, entry = GeneralProductionBuilder._generate_scene_image(
        [(profile, provider)], _scene(), 1, tmp_path, standing_permission=False,
    )

    assert calls["n"] == 1  # never gated
    assert image_path is not None
    assert entry.success is True


# 5: approval-required does not increment provider failure counters or
# trigger cooldown -- the provider was never actually called.
def test_approval_required_does_not_record_provider_failure_or_cooldown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")
    _no_http(monkeypatch)

    provider = AIMLMediaProvider()
    profile = provider.profiles()[0]

    for _ in range(5):  # well past the real cooldown threshold, if it were (mis)counted
        GeneralProductionBuilder._generate_scene_image(
            [(profile, provider)], _scene(), 1, tmp_path, standing_permission=False,
        )

    history = ProviderExecutionHistory()
    assert history.recent_for("aiml", TEXT_TO_IMAGE, limit=10) == []
    health = provider_health("aiml", TEXT_TO_IMAGE, history)
    assert health.status == "HEALTHY"


# 6: a real provider failure AFTER approval still records normal
# failure/cooldown -- the safety fix must not accidentally suppress
# genuine execution-failure tracking once approval is granted.
def test_real_failure_after_approval_still_records_failure_and_cooldown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")

    def fake_post(url, headers=None, json=None, timeout=None):
        response = requests.Response()
        response.status_code = 500
        raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr("requests.post", fake_post)

    provider = AIMLMediaProvider()
    profile = provider.profiles()[0]

    for _ in range(3):
        image_path, entry = GeneralProductionBuilder._generate_scene_image(
            [(profile, provider)], _scene(), 1, tmp_path, standing_permission=True,
        )
        assert image_path is None
        assert not entry.quality_evidence.get("approval_required")

    history = ProviderExecutionHistory()
    assert len(history.recent_for("aiml", TEXT_TO_IMAGE, limit=10)) == 3
    health = provider_health("aiml", TEXT_TO_IMAGE, history)
    assert health.status == "COOLDOWN"


# End-to-end message shape: PackageBuildResult reports APPROVAL_REQUIRED,
# never CAPABILITY_GAP, when the only reason generation didn't happen is
# missing approval (the capability genuinely exists).
def test_build_reports_approval_required_not_capability_gap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "")
    monkeypatch.setattr(Settings, "LTX_API_KEY", "")
    monkeypatch.setattr(Settings, "FAL_API_KEY", "")
    _no_http(monkeypatch)

    from src.media.production import parse_plan_text

    plan_text = (
        "SENARYO\nx\n\nSAHNELER\n"
        "Sahne 1 (~8 sn): Anlatım: a | Görsel: b | Ekran yazısı: c\n"
        "Sahne 2 (~8 sn): Anlatım: a | Görsel: b | Ekran yazısı: c\n"
        "Sahne 3 (~8 sn): Anlatım: a | Görsel: b | Ekran yazısı: c\n"
        "Sahne 4 (~8 sn): Anlatım: a | Görsel: b | Ekran yazısı: c\n\n"
        "SESLENDİRME PLANI\nx\n\nGÖRSEL/VİDEO PLANI\nx\n\nALTYAZI PLANI\nx\n\n"
        "THUMBNAIL FİKRİ\nx\n\nBAŞLIK\nTest\n\nAÇIKLAMA\nx\n\nETİKETLER\na, b\n"
    )
    assert parse_plan_text(plan_text) is not None  # sanity: the fixture plan text is well-formed

    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")
    result = builder.build(goal="Swiss Insider icin bir haber videosu", plan_text=plan_text,
                            memory={}, duration_seconds=32, standing_permission=False)

    assert result.success is False
    assert "APPROVAL_REQUIRED" in result.error
    assert "CAPABILITY_GAP" not in result.error
    assert result.missing_capabilities == ()


# 7: YouTube publish approval is unaffected by this change.
def test_youtube_publish_actions_remain_approval_gated():
    from src.security.action_policy import ActionPolicy

    assert "publish_scheduled_video" in ActionPolicy.MEDIUM_RISK_ACTIONS
    assert "upload_private_video" in ActionPolicy.MEDIUM_RISK_ACTIONS
    assert "publish_scheduled_video" not in ActionPolicy.LOW_RISK_ACTIONS
    assert "upload_private_video" not in ActionPolicy.LOW_RISK_ACTIONS
    decision = ActionPolicy().evaluate("publish_scheduled_video", standing_permission=False)
    assert decision.requires_confirmation is True


# 8: finance risk tiers are unaffected by this change.
def test_finance_action_tiers_remain_unchanged():
    from src.security.action_policy import ActionPolicy

    assert "paper_trade" in ActionPolicy.LOW_RISK_ACTIONS
    assert "live_trade" in ActionPolicy.HIGH_RISK_ACTIONS
    assert "withdraw_money" in ActionPolicy.CRITICAL_ACTIONS
    assert "transfer_money" in ActionPolicy.CRITICAL_ACTIONS
    live_trade = ActionPolicy().evaluate("live_trade", standing_permission=True)
    assert live_trade.requires_confirmation is True  # never bypassed by standing_permission
