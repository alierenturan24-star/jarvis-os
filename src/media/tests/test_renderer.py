import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.media.renderer import LocalVideoRenderer, _motion_spec_for_scene, find_ffmpeg, validate_video_artifact


def test_renderer_reports_missing_ffmpeg_without_fake_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr("src.media.renderer.find_ffmpeg", lambda: None)
    result = LocalVideoRenderer(tmp_path).render("test", "narration", 2)
    assert not result.success
    assert result.artifact_path == ""
    assert "FFmpeg" in result.error
    assert not list(tmp_path.rglob("*.mp4"))


def test_video_validator_rejects_nonzero_fake_mp4(tmp_path):
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"not a video" * 200)
    assert not validate_video_artifact(fake)


def test_video_validator_accepts_minimal_mp4_signature_without_probe(tmp_path, monkeypatch):
    candidate = tmp_path / "real-shape.mp4"
    candidate.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"x" * 2048)
    monkeypatch.setattr("src.media.renderer.find_ffprobe", lambda: None)
    assert validate_video_artifact(candidate)


def test_motion_spec_requires_authored_pose_sequence():
    manifest = {"character_motion": [{
        "scene_file": "run.png", "pose_files": ["run-a.png", "run-b.png"]
    }]}
    assert _motion_spec_for_scene(manifest, "run.png")["pose_files"] == ["run-a.png", "run-b.png"]
    assert _motion_spec_for_scene(manifest, "other.png") is None


def test_renderer_mixes_original_music_and_embeds_subtitles(tmp_path, monkeypatch):
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg unavailable")
    package_root = tmp_path / "package"
    package_root.mkdir()
    scene = package_root / "scene.png"
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
        "testsrc2=size=1080x1920:rate=1", "-frames:v", "1", str(scene),
    ], check=True, timeout=30)
    scene_names = []
    for index in range(4):
        target = package_root / f"scene-{index}.png"
        shutil.copy2(scene, target)
        scene_names.append(target.name)
    audio = package_root / "narration.wav"
    music = package_root / "music.wav"
    for target, frequency in ((audio, 330), (music, 110)):
        subprocess.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            f"sine=frequency={frequency}:sample_rate=44100:duration=2", str(target),
        ], check=True, timeout=30)
    subtitles = package_root / "subtitles.srt"
    subtitles.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHallo Schweiz\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nBleib informiert\n",
        encoding="utf-8",
    )
    manifest = package_root / "production.json"
    manifest.write_text(json.dumps({
        "placeholder": False, "fallback": False, "goal": "Swiss test",
        "scene_files": scene_names, "audio_file": audio.name, "music_file": music.name,
        "subtitle_file": subtitles.name, "channel_language": "de-CH", "narration_seconds": 2,
        "scene_plan": [{"duration_seconds": 0.5} for _ in scene_names],
        "story_beats": ["HOOK", "SETUP", "CLIMAX", "RESOLUTION"],
    }), encoding="utf-8")
    monkeypatch.setattr("src.media.renderer._find_production_package", lambda topic: manifest)

    result = LocalVideoRenderer(tmp_path / "artifacts").render("Swiss test", "narration", 2)

    assert result.success, result.error
    probe = subprocess.run([
        shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
        "-of", "default=nw=1:nk=1", result.artifact_path,
    ], capture_output=True, text=True, check=True, timeout=30)
    assert "video" in probe.stdout
    assert "audio" in probe.stdout
    assert "subtitle" in probe.stdout
