from __future__ import annotations

from src.media.quality import REQUIRED_SECTIONS, check_media_plan_quality
from src.media.quality import validate_media_goal_artifact
from src.media.renderer import find_ffmpeg
import json
import subprocess


def _complete_plan() -> str:
    return "\n\n".join(f"{section}\n{'kelime ' * 6}" for section in REQUIRED_SECTIONS)


class TestCheckMediaPlanQuality:
    def test_complete_plan_with_all_sections_passes(self):
        check = check_media_plan_quality(_complete_plan())
        assert check.passed is True
        assert check.missing_sections == ()

    def test_missing_section_is_detected(self):
        plan = _complete_plan().replace("THUMBNAIL FİKRİ", "")
        check = check_media_plan_quality(plan)
        assert check.passed is False
        assert "THUMBNAIL FİKRİ" in check.missing_sections

    def test_empty_text_fails_with_all_sections_missing(self):
        check = check_media_plan_quality("")
        assert check.passed is False
        assert check.missing_sections == REQUIRED_SECTIONS

    def test_too_short_text_fails_even_with_all_headers(self):
        plan = "\n".join(REQUIRED_SECTIONS)  # başlıklar var ama içerik yok
        check = check_media_plan_quality(plan)
        assert check.passed is False
        assert "kısa" in check.summary.lower()

    def test_none_input_does_not_crash(self):
        check = check_media_plan_quality(None)  # type: ignore[arg-type]
        assert check.passed is False


def test_technical_video_without_production_provenance_fails_semantic_quality(tmp_path):
    video = tmp_path / "technical-only.mp4"
    subprocess.run([
        find_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", "-f", "lavfi", "-i", "anullsrc",
        "-shortest", "-pix_fmt", "yuv420p", str(video),
    ], check=True, timeout=15)
    result = validate_media_goal_artifact(video, "Video üret.")
    assert result.technical_passed is True
    assert result.semantic_passed is False
    assert "production quality provenance missing" in result.issues


def test_placeholder_provenance_fails_even_when_claimed_ready(tmp_path):
    video = tmp_path / "placeholder.mp4"
    subprocess.run([
        find_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=s=64x64:d=1", "-f", "lavfi", "-i", "sine=d=1",
        "-shortest", "-pix_fmt", "yuv420p", str(video),
    ], check=True, timeout=15)
    video.with_suffix(".quality.json").write_text(json.dumps({
        "goal": "Video üret.", "production_ready": True, "placeholder": True,
        "fallback": False, "production_backend": "placeholder", "scene_count": 6,
        "story_beats": ["a", "b", "c", "d", "e", "f"], "script_coverage": True,
        "audio_present": True,
    }), encoding="utf-8")
    result = validate_media_goal_artifact(video, "Video üret.")
    assert result.semantic_passed is False
    assert "placeholder/fallback artifact" in result.issues
