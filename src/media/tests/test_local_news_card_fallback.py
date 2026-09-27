import json
import wave
from pathlib import Path

import pytest

from src.media.capability_model import MediaModelProfile, SceneProvenance, TEXT_TO_IMAGE
from src.media.production import GeneralProductionBuilder, ParsedProductionPlan, ScenePlan
from src.media.renderer import LocalVideoRenderer, find_ffmpeg


def test_local_news_card_creates_original_free_vertical_scene(tmp_path):
    if not Path(find_ffmpeg()).is_file():
        pytest.skip("ffmpeg unavailable")
    scene = ScenePlan(
        scene_id="scene-1", script_beat_id="HOOK", purpose="hook",
        narration_segment="İsviçre'de bugün ulaşımı etkileyen önemli değişiklik açıklandı.",
        visual_description="Swiss transport news graphic",
        duration_seconds=6.0, caption_text="İsviçre'de ulaşım değişikliği",
    )

    path, provenance = GeneralProductionBuilder._build_local_news_card(scene, 1, tmp_path)

    assert path is not None and path.is_file() and path.stat().st_size > 10_000
    assert provenance.success is True
    assert provenance.provider == "local_ffmpeg_motion_graphics"
    assert provenance.cost_class == "free"
    assert provenance.quality_evidence["license"] == "original"
    assert provenance.quality_evidence["external_media_used"] is False


def test_free_only_package_continues_when_commons_has_no_scene(tmp_path, monkeypatch):
    if not Path(find_ffmpeg()).is_file():
        pytest.skip("ffmpeg unavailable")
    scenes = tuple(
        ScenePlan(
            scene_id=f"scene-{index:02d}", script_beat_id="HOOK", purpose="news",
            narration_segment=f"Doğrulanmış haber sahnesi {index}.",
            visual_description=f"Swiss news scene {index}", duration_seconds=1.0,
            caption_text=f"Güncel gelişme {index}",
        )
        for index in range(1, 5)
    )
    parsed = ParsedProductionPlan(
        hook=scenes[0].narration_segment,
        script=" ".join(scene.narration_segment for scene in scenes),
        ending=scenes[-1].narration_segment, scenes=scenes,
        title="İsviçre Güncel Haber Testi", description="Kaynaklı test",
        tags=("İsviçre", "haber"), thumbnail_concept="İsviçre gündemi",
    )
    profile = MediaModelProfile(
        provider_id="wikimedia_commons", model_id="licensed-media-search-v1",
        capabilities=(TEXT_TO_IMAGE,), availability=True, auth_required=False,
        cost_class="free", free_tier=True, subscription_cli=False,
        local_or_remote="remote", quality_tier=60, speed_tier=50,
    )
    monkeypatch.setattr(
        "src.media.production.rank_available_providers",
        lambda *args, **kwargs: ([(profile, object())], []),
    )
    monkeypatch.setattr(
        GeneralProductionBuilder, "_licensed_commons_clip",
        staticmethod(lambda *args, **kwargs: (None, None)),
    )

    def failed_provider(ranked, scene, index, root, **kwargs):
        return None, SceneProvenance(
            scene_id=scene.scene_id, capability=TEXT_TO_IMAGE,
            provider="wikimedia_commons", model="licensed-media-search-v1",
            generation_type=TEXT_TO_IMAGE, output_path="", success=False,
            quality_evidence={"reason": "no licensed result"},
        )

    monkeypatch.setattr(GeneralProductionBuilder, "_generate_scene_image", staticmethod(failed_provider))

    def local_audio(root, script, language, voice):
        target = root / "narration.wav"
        with wave.open(str(target), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16_000)
            handle.writeframes(b"\0\0" * 16_000 * 4)
        return target, "local-test-voice", True

    monkeypatch.setattr("src.media.production.write_narration_audio", local_audio)
    builder = GeneralProductionBuilder(output_root=tmp_path / "generated")

    result = builder._build_via_dynamic_provider(
        goal="İsviçre güncel haber", parsed=parsed, memory={}, channel_id="default",
        channel_market="Switzerland", channel_language="tr-TR", research_grounded=True,
        research_evidence_ref={"source_count": 2}, required=("scene_generation",),
        available=(), missing=("scene_generation",), free_only=True,
    )

    assert result.success is True, result.error
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["fallback"] is False
    assert manifest["placeholder"] is False
    assert manifest["local_original_scenes_used"] is True
    assert len(manifest["scene_files"]) == 4
    assert all(row["provider"] == "local_ffmpeg_motion_graphics" for row in manifest["scene_provenance"])

    rendered = LocalVideoRenderer(output_root=tmp_path / "artifacts")._render_production_package(
        Path(result.manifest_path), parsed.title, 4, find_ffmpeg(),
    )
    assert rendered.success is True, rendered.error
    assert Path(rendered.artifact_path).is_file()
    assert Path(rendered.artifact_path).stat().st_size > 10_000
