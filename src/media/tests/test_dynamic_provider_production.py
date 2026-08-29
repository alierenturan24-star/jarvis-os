from __future__ import annotations

import json
import shutil
from pathlib import Path

from src.config.settings import Settings
from src.media.capability_model import IMAGE_TO_VIDEO, MediaGenerationResult, MediaModelProfile, TEXT_TO_IMAGE
from src.media.production import GeneralProductionBuilder
from src.providers.media_provider_base import MediaProvider
from src.providers.nvidia_provider import NvidiaMediaProvider


class _FakeImageProvider(MediaProvider):
    """Second, independent text_to_image candidate used only to prove the
    per-scene fallback chain (Phase 8: a provider execution failure must
    trigger trying another compatible provider) -- distinct from NVIDIA,
    which is the only real text_to_image provider implemented in this pass."""

    def __init__(self, provider_id: str, quality_tier: int, generate_fn):
        super().__init__(provider_id)
        self._quality_tier = quality_tier
        self._generate_fn = generate_fn

    def capabilities(self):
        return (TEXT_TO_IMAGE,)

    def is_available(self):
        return True

    def unavailable_reason(self):
        return ""

    def profiles(self):
        return (MediaModelProfile(
            provider_id=self.provider_id, model_id=f"{self.provider_id}-model",
            capabilities=(TEXT_TO_IMAGE,), availability=True, auth_required=True,
            cost_class="paid", free_tier=False, subscription_cli=False, local_or_remote="remote",
            quality_tier=self._quality_tier, speed_tier=70),)

    def generate_image(self, prompt, **kwargs):
        return self._generate_fn(prompt, **kwargs)


class _FakeVideoProvider(MediaProvider):
    """Second capability family (image_to_video) used only to exercise the
    OPT-IN scene-motion chain (GeneralProductionBuilder._maybe_generate_
    scene_motion) -- distinct from the text_to_image fakes above."""

    def __init__(self, provider_id: str, generate_fn):
        super().__init__(provider_id)
        self._generate_fn = generate_fn

    def capabilities(self):
        return (IMAGE_TO_VIDEO,)

    def is_available(self):
        return True

    def unavailable_reason(self):
        return ""

    def profiles(self):
        return (MediaModelProfile(
            provider_id=self.provider_id, model_id=f"{self.provider_id}-model",
            capabilities=(IMAGE_TO_VIDEO,), availability=True, auth_required=True,
            cost_class="paid", free_tier=False, subscription_cli=False, local_or_remote="remote",
            quality_tier=80, speed_tier=60),)

    def generate_video_from_image(self, prompt, image_url, **kwargs):
        return self._generate_fn(prompt, image_url, **kwargs)


_PLAN_TEXT = """SENARYO
Isvicre'de hibrit calisma modeli hizla yayiliyor ve verimliligi artiriyor.

SAHNELER
Sahne 1 (~8 sn): Anlatım: Isvicre'de yeni bir is trendi | Görsel: Isvicre sehir manzarasi, ofis binalari | Ekran yazısı: Trend basliyor
Sahne 2 (~8 sn): Anlatım: Ofis ve ev arasinda denge | Görsel: Evden calisan kisi | Ekran yazısı: Denge
Sahne 3 (~8 sn): Anlatım: Verimlilik artiyor | Görsel: Yukselen grafik | Ekran yazısı: Verimlilik
Sahne 4 (~8 sn): Anlatım: Gelecek burada | Görsel: Mutlu calisanlar | Ekran yazısı: Gelecek

SESLENDİRME PLANI
Windows System.Speech kullanilacak.

GÖRSEL/VİDEO PLANI
Dinamik provider ile uretilecek.

ALTYAZI PLANI
Sahne zamanlamasina gore.

THUMBNAIL FİKRİ
Yukselen grafik ve mutlu calisanlar

BAŞLIK
Hibrit Calisma Modeli Yukseliyor

AÇIKLAMA
Isvicre'de hibrit calisma modelinin yukselisini anlatan kisa video.

ETİKETLER
isvicre, hibrit, calisma, verimlilik
"""


def _fake_success(content: bytes = b"x" * 5000):
    def _generate(self, prompt, *, width=1024, height=1024, seed=0, model=None):
        return MediaGenerationResult(True, "nvidia", Settings.NVIDIA_IMAGE_MODEL, TEXT_TO_IMAGE,
                                      content_bytes=content, seed_used=seed, duration_seconds=0.1,
                                      cost_class="paid")
    return _generate


def _fake_success_with_url(content: bytes = b"x" * 5000, url: str = "https://cdn.fal.ai/fake/img.png"):
    """Like _fake_success but also returns a hosted content_url -- the fal
    FLUX-shaped result (real fal responses always include one), unlike
    NVIDIA which returns base64 only. Motion-chaining
    (_maybe_generate_scene_motion) requires this URL."""
    def _generate(prompt, **kwargs):
        return MediaGenerationResult(True, "img-provider", "img-provider-model", TEXT_TO_IMAGE,
                                      content_bytes=content, content_url=url, duration_seconds=0.1,
                                      cost_class="paid")
    return _generate


# F: genuine visual capability available (mocked) -> production path
# continues normally (no CAPABILITY_GAP, real manifest/scene files written).
#
# NOTE: every test below monkeypatch.chdir(tmp_path) -- GeneralProductionBuilder
# generation calls record through the REAL, process-wide
# ProviderExecutionHistory (workspace/knowledge/provider_execution_history.json,
# relative to CWD, by design -- no second history store). Without chdir these
# tests would pollute that real, persisted file with fake provider/test rows.
def test_available_dynamic_provider_produces_real_manifest_and_scenes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(NvidiaMediaProvider, "generate_image", _fake_success())
    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")

    result = builder.build(goal="Swiss Insider icin hibrit calisma haberi", plan_text=_PLAN_TEXT,
                            memory={}, duration_seconds=32, channel_id="youtube-ch",
                            channel_market="Switzerland", channel_language="de-CH",
                            standing_permission=True)

    assert result.success is True, result.error
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["production_backend"].startswith("dynamic_provider:nvidia")
    assert manifest["characters"] == []  # no fabricated character identity
    assert len(manifest["scene_files"]) == 4
    root = Path(result.manifest_path).parent
    for name in manifest["scene_files"]:
        path = root / name
        assert path.is_file() and path.stat().st_size >= 5000
    assert len(manifest["scene_provenance"]) == 4
    for entry in manifest["scene_provenance"]:
        assert entry["provider"] == "nvidia"
        assert entry["success"] is True
        # no API key/secret ever persisted into provenance
        assert "test-key-not-real" not in json.dumps(entry)


# Capability accounting: a successful dynamic-provider build reports all
# required capabilities as genuinely available this run, never merely
# declared from a static list.
def test_available_dynamic_provider_reports_full_capability_accounting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(NvidiaMediaProvider, "generate_image", _fake_success())
    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")

    result = builder.build(goal="Swiss Insider icin hibrit calisma haberi", plan_text=_PLAN_TEXT,
                            memory={}, duration_seconds=32, standing_permission=True)

    assert result.missing_capabilities == ()
    assert "character_visual_generation" in result.available_capabilities


# I: provider execution failure triggers the existing fallback chain -- the
# top-ranked candidate failing must not fail the whole build when a second,
# lower-ranked compatible provider is genuinely available and succeeds
# (bounded to the top 2 ranked candidates per scene, see
# GeneralProductionBuilder._generate_scene_image).
def test_top_ranked_provider_failure_falls_back_to_next_candidate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = {"a": 0, "b": 0}

    def _always_fails(prompt, **kwargs):
        calls["a"] += 1
        return MediaGenerationResult(False, "provider-a", "model-a", TEXT_TO_IMAGE,
                                      error="provider A execution failed", cost_class="paid")

    def _always_succeeds(prompt, **kwargs):
        calls["b"] += 1
        return MediaGenerationResult(True, "provider-b", "model-b", TEXT_TO_IMAGE,
                                      content_bytes=b"z" * 5000, cost_class="paid")

    # provider-a ranks first (higher quality_tier); provider-b is the
    # fallback -- both genuinely "available" (is_available() True), so this
    # exercises real EXECUTION failure triggering fallback, not an
    # availability filter.
    provider_a = _FakeImageProvider("provider-a", quality_tier=95, generate_fn=_always_fails)
    provider_b = _FakeImageProvider("provider-b", quality_tier=60, generate_fn=_always_succeeds)
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (provider_a, provider_b))
    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")

    result = builder.build(goal="Swiss Insider icin hibrit calisma haberi", plan_text=_PLAN_TEXT,
                            memory={}, duration_seconds=32, standing_permission=True)

    assert result.success is True, result.error
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert all(entry["provider"] == "provider-b" for entry in manifest["scene_provenance"])
    assert all(entry["fallback_used"] is True for entry in manifest["scene_provenance"])
    assert calls["a"] == 4  # one attempt per scene, all failed
    assert calls["b"] == 4  # fallback succeeded for every scene


# K: all compatible providers unavailable -> CAPABILITY_GAP, citing the
# real considered candidates (not a generic message).
def test_no_available_provider_returns_capability_gap_with_considered_candidates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "")
    monkeypatch.setattr(Settings, "LTX_API_KEY", "")
    # AIML (src.providers.aiml_media_provider) is a THIRD real
    # text_to_image candidate -- must also be disabled for this scenario
    # to genuinely mean "no provider available" regardless of which real
    # keys happen to be configured in the running environment.
    monkeypatch.setattr(Settings, "AIML_API_KEY", "")
    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")

    result = builder.build(goal="Swiss Insider icin hibrit calisma haberi", plan_text=_PLAN_TEXT,
                            memory={}, duration_seconds=32)

    assert result.success is False
    assert "CAPABILITY_GAP" in result.error
    assert "character_visual_generation" in result.missing_capabilities


# L: legacy Leni assets are not silently used even when a dynamic provider
# happens to be unavailable at the same time -- the goal never unlocks them
# implicitly, only the explicit allow_legacy_authored_series flag does.
def test_dynamic_path_never_falls_back_to_legacy_assets_implicitly(tmp_path, monkeypatch):
    real_source = Path("workspace/assets/media/channel-default-sources").resolve()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "")
    monkeypatch.setattr(Settings, "LTX_API_KEY", "")
    monkeypatch.setattr(Settings, "AIML_API_KEY", "")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    for suffix in ("-storyboard.png", "-running-poses.png"):
        shutil.copy2(real_source / f"lantern{suffix}", source_root / f"lantern{suffix}")
    builder = GeneralProductionBuilder(source_root=source_root, output_root=tmp_path / "generated")

    result = builder.build(goal="Leni icin bir video (mentions leni but does not opt in)",
                            plan_text=_PLAN_TEXT, memory={}, duration_seconds=32)

    assert result.success is False
    assert "CAPABILITY_GAP" in result.error
    assert not list((tmp_path / "generated").rglob("production.json"))


# Pipeline integration (requirement 14): enable_scene_motion is OPT-IN --
# disabled by default, no image_to_video call is ever attempted even when a
# compatible provider exists, and every scene stays a still image (the
# existing, already-verified zoompan-driven behavior above).
def test_scene_motion_not_attempted_when_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    video_calls = {"n": 0}

    def _video_generate(prompt, image_url, **kwargs):
        video_calls["n"] += 1
        return MediaGenerationResult(True, "video-provider", "video-model", IMAGE_TO_VIDEO,
                                      content_bytes=b"v" * 20000, cost_class="paid")

    image_provider = _FakeImageProvider("img-provider", quality_tier=80, generate_fn=_fake_success_with_url())
    video_provider = _FakeVideoProvider("video-provider", generate_fn=_video_generate)
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (image_provider, video_provider))
    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")

    result = builder.build(goal="Swiss Insider icin hibrit calisma haberi", plan_text=_PLAN_TEXT,
                            memory={}, duration_seconds=32,  # enable_scene_motion defaults False
                            standing_permission=True)

    assert result.success is True, result.error
    assert video_calls["n"] == 0
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert all(entry["capability"] == TEXT_TO_IMAGE for entry in manifest["scene_provenance"])
    assert all(name.endswith(".png") for name in manifest["scene_files"])


# When explicitly enabled AND the image provider returns a real hosted URL
# for its own output (fal FLUX-shaped), a genuinely compatible
# image_to_video provider is chained for real scene motion.
def test_enable_scene_motion_chains_image_to_video_when_url_available(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    video_calls = {"n": 0}

    def _video_generate(prompt, image_url, **kwargs):
        video_calls["n"] += 1
        # Succeed only for the FIRST scene -- keeps the LAST scene a still
        # image so the thumbnail path is exercised without needing a real
        # (ffmpeg-decodable) video file in this test.
        if video_calls["n"] == 1:
            assert image_url == "https://cdn.fal.ai/fake/img.png"
            return MediaGenerationResult(True, "video-provider", "video-model", IMAGE_TO_VIDEO,
                                          content_bytes=b"v" * 20000, cost_class="paid")
        return MediaGenerationResult(False, "video-provider", "video-model", IMAGE_TO_VIDEO,
                                      error="simulated failure for remaining scenes", cost_class="paid")

    image_provider = _FakeImageProvider("img-provider", quality_tier=80, generate_fn=_fake_success_with_url())
    video_provider = _FakeVideoProvider("video-provider", generate_fn=_video_generate)
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (image_provider, video_provider))
    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")

    result = builder.build(goal="Swiss Insider icin hibrit calisma haberi", plan_text=_PLAN_TEXT,
                            memory={}, duration_seconds=32, enable_scene_motion=True,
                            standing_permission=True)

    assert result.success is True, result.error
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    provenance = manifest["scene_provenance"]
    video_entries = [entry for entry in provenance if entry["capability"] == IMAGE_TO_VIDEO]
    still_entries = [entry for entry in provenance if entry["capability"] == TEXT_TO_IMAGE]
    assert len(video_entries) == 1
    assert len(still_entries) == 3
    assert video_entries[0]["provider"] == "video-provider"
    root = Path(result.manifest_path).parent
    for name in manifest["scene_files"]:
        assert (root / name).is_file()
    assert any(name.endswith(".mp4") for name in manifest["scene_files"])
    assert (root / "thumbnail-final.png").is_file()
    assert (root / "thumbnail-final.png").stat().st_size >= 5000  # a real still, not raw video bytes


# When the image provider does not return a hosted URL (NVIDIA -- base64
# only), motion generation is never attempted even with enable_scene_motion
# on: never invent an upload step, just keep the deterministic still path.
def test_scene_motion_skipped_when_image_provider_has_no_hosted_url(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(NvidiaMediaProvider, "generate_image", _fake_success())  # no content_url
    video_calls = {"n": 0}

    def _video_generate(prompt, image_url, **kwargs):
        video_calls["n"] += 1
        return MediaGenerationResult(True, "video-provider", "video-model", IMAGE_TO_VIDEO,
                                      content_bytes=b"v" * 20000, cost_class="paid")

    video_provider = _FakeVideoProvider("video-provider", generate_fn=_video_generate)
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (NvidiaMediaProvider(), video_provider))
    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")

    result = builder.build(goal="Swiss Insider icin hibrit calisma haberi", plan_text=_PLAN_TEXT,
                            memory={}, duration_seconds=32, enable_scene_motion=True,
                            standing_permission=True)

    assert result.success is True, result.error
    assert video_calls["n"] == 0
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert all(entry["capability"] == TEXT_TO_IMAGE for entry in manifest["scene_provenance"])


# A failed motion attempt must never fail the build -- it is a bonus
# enhancement, so the already-generated still image is kept.
def test_scene_motion_failure_falls_back_to_still_image(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def _video_generate(prompt, image_url, **kwargs):
        return MediaGenerationResult(False, "video-provider", "video-model", IMAGE_TO_VIDEO,
                                      error="simulated failure", cost_class="paid")

    image_provider = _FakeImageProvider("img-provider", quality_tier=80, generate_fn=_fake_success_with_url())
    video_provider = _FakeVideoProvider("video-provider", generate_fn=_video_generate)
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (image_provider, video_provider))
    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")

    result = builder.build(goal="Swiss Insider icin hibrit calisma haberi", plan_text=_PLAN_TEXT,
                            memory={}, duration_seconds=32, enable_scene_motion=True,
                            standing_permission=True)

    assert result.success is True, result.error
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert all(entry["capability"] == TEXT_TO_IMAGE for entry in manifest["scene_provenance"])
    assert all(name.endswith(".png") for name in manifest["scene_files"])
