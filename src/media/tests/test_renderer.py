from pathlib import Path

from src.media.renderer import LocalVideoRenderer, _motion_spec_for_scene, validate_video_artifact


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
