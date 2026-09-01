from __future__ import annotations

import json
from pathlib import Path

from src.config.settings import Settings
from src.media.capability_model import IMAGE_TO_VIDEO, MediaGenerationResult, MediaModelProfile, TEXT_TO_IMAGE
from src.media.manager import MediaManager
from src.media.production import GeneralProductionBuilder
from src.providers.aiml_media_provider import AIMLMediaProvider
from src.providers.media_provider_base import MediaProvider

# Sprint: cloud-media capability wiring. A plain "generate an image" request
# (no youtube/video/short wording) previously never reached the existing
# ranked-provider/approval/provenance pipeline -- MediaAgent only set
# produce_artifact=True for full YouTube Short production intent, and no
# lightweight single-asset entrypoint existed (running the full multi-scene
# Shorts builder for a single image ask would be wrong). This file tests the
# new GeneralProductionBuilder.build_standalone_asset/MediaManager.
# generate_asset wiring, which reuses the EXISTING rank_available_providers,
# _generate_scene_image (ranking + per-call paid-media approval gate +
# generate+save+provenance), and SceneProvenance -- no second provider/
# artifact/approval system. Mocks only -- no real network/paid calls.


class _FakeImageProvider(MediaProvider):
    def __init__(self, provider_id: str, quality_tier: int, generate_fn, cost_class: str = "paid",
                 model_id: str | None = None):
        super().__init__(provider_id)
        self._quality_tier = quality_tier
        self._generate_fn = generate_fn
        self._cost_class = cost_class
        self._model_id = model_id or f"{provider_id}-model"

    def capabilities(self):
        return (TEXT_TO_IMAGE,)

    def is_available(self):
        return True

    def unavailable_reason(self):
        return ""

    def profiles(self):
        return (MediaModelProfile(
            provider_id=self.provider_id, model_id=self._model_id,
            capabilities=(TEXT_TO_IMAGE,), availability=True, auth_required=True,
            cost_class=self._cost_class, free_tier=False, subscription_cli=False, local_or_remote="remote",
            quality_tier=self._quality_tier, speed_tier=70),)

    def generate_image(self, prompt, **kwargs):
        return self._generate_fn(prompt, **kwargs)


def _no_http(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("no real HTTP call should happen without approval")
    monkeypatch.setattr("requests.post", _boom)
    monkeypatch.setattr("requests.get", _boom)


# 1: an eligible cloud provider is selected through the EXISTING registry
# (rank_available_providers) and its output becomes a real local artifact
# file (exists, non-empty, usable) -- not just a URL/"success" string.
def test_eligible_provider_selected_and_output_becomes_real_local_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"images": [{"url": "https://cdn.aimlapi.com/x.png"}], "seed": 1}

    def fake_post(url, headers=None, json=None, timeout=None):
        return _Response()

    def fake_get(url, timeout=None):
        return type("R", (), {"raise_for_status": lambda self: None, "content": b"x" * 5000})()

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.get", fake_get)

    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")
    result = builder.build_standalone_asset(
        goal="a swiss mountain village at sunrise", capability=TEXT_TO_IMAGE,
        channel_id="default", standing_permission=True,
    )

    assert result.success is True, result.error
    artifact = Path(result.manifest_path)
    assert artifact.is_file()
    assert artifact.stat().st_size >= 5000


# 2: provenance (provider/model/capability/goal) is retained alongside the
# artifact -- both on the returned result and in the persisted manifest.
def test_artifact_provenance_is_retained(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def _succeeds(prompt, **kwargs):
        return MediaGenerationResult(True, "provider-a", "model-a", TEXT_TO_IMAGE,
                                      content_bytes=b"y" * 5000, cost_class="paid")

    provider = _FakeImageProvider("provider-a", quality_tier=90, generate_fn=_succeeds, model_id="model-a")
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (provider,))
    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")

    result = builder.build_standalone_asset(
        goal="a red bicycle", capability=TEXT_TO_IMAGE, channel_id="default", standing_permission=True,
    )

    assert result.success is True, result.error
    manifest_files = list((tmp_path / "generated" / "default").glob("asset-*/asset.json"))
    assert len(manifest_files) == 1
    manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
    assert manifest["capability"] == TEXT_TO_IMAGE
    assert manifest["goal"] == "a red bicycle"
    assert manifest["provenance"]["provider"] == "provider-a"
    assert manifest["provenance"]["model"] == "model-a"
    assert manifest["provenance"]["success"] is True
    assert Path(manifest["artifact_path"]).is_file()


# 3: fallback provider used when the first (top-ranked) provider fails --
# reuses the existing per-scene fallback chain (_generate_scene_image),
# proven here through the new standalone entrypoint specifically.
def test_fallback_provider_used_when_first_provider_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = {"a": 0, "b": 0}

    def _fails(prompt, **kwargs):
        calls["a"] += 1
        return MediaGenerationResult(False, "provider-a", "model-a", TEXT_TO_IMAGE,
                                      error="provider A execution failed", cost_class="paid")

    def _succeeds(prompt, **kwargs):
        calls["b"] += 1
        return MediaGenerationResult(True, "provider-b", "model-b", TEXT_TO_IMAGE,
                                      content_bytes=b"z" * 5000, cost_class="paid")

    provider_a = _FakeImageProvider("provider-a", quality_tier=95, generate_fn=_fails)
    provider_b = _FakeImageProvider("provider-b", quality_tier=60, generate_fn=_succeeds)
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (provider_a, provider_b))
    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")

    result = builder.build_standalone_asset(
        goal="a mountain lake", capability=TEXT_TO_IMAGE, channel_id="default", standing_permission=True,
    )

    assert result.success is True, result.error
    assert calls["a"] == 1
    assert calls["b"] == 1
    manifest = json.loads(Path(result.manifest_path).with_name("asset.json").read_text(encoding="utf-8"))
    assert manifest["provenance"]["provider"] == "provider-b"
    assert manifest["provenance"]["fallback_used"] is True


# 4: no paid provider call happens before approval -- zero HTTP calls, and
# the result is an honest APPROVAL_REQUIRED (not a fabricated CAPABILITY_GAP).
def test_no_paid_provider_call_before_approval(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")
    _no_http(monkeypatch)
    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")

    result = builder.build_standalone_asset(
        goal="a swiss mountain village", capability=TEXT_TO_IMAGE, channel_id="default",
        standing_permission=False,
    )

    assert result.success is False
    assert "APPROVAL_REQUIRED" in result.error
    assert "CAPABILITY_GAP" not in result.error


# 5: once approved (same mission/task, standing_permission=True for that one
# call), generation proceeds to real artifact creation.
def test_approved_same_call_continues_to_artifact_creation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"images": [{"url": "https://cdn.aimlapi.com/x.png"}], "seed": 1}

    monkeypatch.setattr("requests.post", lambda *a, **k: _Response())
    monkeypatch.setattr("requests.get", lambda *a, **k: type(
        "R", (), {"raise_for_status": lambda self: None, "content": b"x" * 5000})())

    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")
    result = builder.build_standalone_asset(
        goal="a swiss mountain village", capability=TEXT_TO_IMAGE, channel_id="default",
        standing_permission=True,
    )

    assert result.success is True, result.error
    assert Path(result.manifest_path).is_file()


# 6: MediaManager.generate_asset surfaces the same capability-gap/approval
# reporting contract as plan()/build() -- honest, not fabricated.
def test_manager_generate_asset_reports_capability_gap_when_no_provider_available(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "AIML_API_KEY", "")
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "")
    monkeypatch.setattr(Settings, "FAL_API_KEY", "")
    monkeypatch.setattr(Settings, "LTX_API_KEY", "")

    manager = MediaManager()
    result = manager.generate_asset("a red bicycle", TEXT_TO_IMAGE)

    assert "CAPABILITY_GAP" in result
    assert manager.last_artifact_path == ""
    assert manager.last_capability_gap is not None
    assert manager.last_capability_gap["missing_capabilities"] == [TEXT_TO_IMAGE]


# 7: post-write existence/usability verification -- a provider "success" is
# not trusted blindly; if the resulting file is missing or empty the build
# reports CAPABILITY_GAP instead of a fabricated artifact path.
def test_build_verifies_artifact_exists_and_is_non_empty_after_generation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from src.media.capability_model import SceneProvenance

    def _fake_generate_scene_image(ranked, scene, index, root, *, enable_motion=False,
                                    stage_sink=None, standing_permission=False):
        empty_path = root / "scene-01.png"
        empty_path.write_bytes(b"")  # simulate a truncated/corrupted write
        return empty_path, SceneProvenance(
            scene_id=scene.scene_id, capability=TEXT_TO_IMAGE, provider="provider-a", model="model-a",
            generation_type=TEXT_TO_IMAGE, output_path=str(empty_path), success=True, fallback_used=False)

    monkeypatch.setattr(GeneralProductionBuilder, "_generate_scene_image", staticmethod(_fake_generate_scene_image))

    def _succeeds(prompt, **kwargs):
        return MediaGenerationResult(True, "provider-a", "model-a", TEXT_TO_IMAGE,
                                      content_bytes=b"y" * 5000, cost_class="paid")
    provider = _FakeImageProvider("provider-a", quality_tier=90, generate_fn=_succeeds)
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (provider,))

    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")
    result = builder.build_standalone_asset(
        goal="a red bicycle", capability=TEXT_TO_IMAGE, channel_id="default", standing_permission=True,
    )

    assert result.success is False
    assert "CAPABILITY_GAP" in result.error
    assert "no usable artifact file" in result.error


# 8: an unsupported capability (e.g. image_to_video, which has no source
# image for a from-scratch standalone request) is an honest CAPABILITY_GAP,
# never silently routed to an unrelated/untested provider call.
def test_unsupported_standalone_capability_is_capability_gap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")

    result = builder.build_standalone_asset(
        goal="a mountain lake", capability=IMAGE_TO_VIDEO, channel_id="default", standing_permission=True,
    )

    assert result.success is False
    assert "CAPABILITY_GAP" in result.error


# 9: structural guarantee -- nothing in the real media provider registry
# offers a local/GPU-backed text_to_image capability, so the standalone
# asset path can only ever reach cloud/API providers. No heavy local model
# is installed or required, and no CUDA/GPU dependency is introduced.
def test_no_local_gpu_backed_text_to_image_provider_is_registered():
    from src.media.provider_selection import _PROVIDERS
    for provider in _PROVIDERS:
        for profile in provider.profiles():
            if TEXT_TO_IMAGE in profile.capabilities:
                assert profile.local_or_remote != "local", (
                    f"{profile.provider_id}/{profile.model_id} unexpectedly claims local text_to_image capability"
                )


# 10: real AIML provider profile is genuinely reused (not re-implemented) by
# the standalone path -- same registered provider instance the Shorts
# pipeline already uses.
def test_real_aiml_provider_is_reused_for_standalone_capability_selection(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "AIML_API_KEY", "test-key-not-real")
    from src.media.provider_selection import rank_available_providers
    ranked, _considered = rank_available_providers(TEXT_TO_IMAGE)
    assert any(isinstance(provider, AIMLMediaProvider) for _profile, provider in ranked)
