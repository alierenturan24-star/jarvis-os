from __future__ import annotations

import json
import subprocess
from pathlib import Path

from src.media.quality import validate_media_goal_artifact
from src.media.renderer import find_ffmpeg

# Sprint: real-production quality-gate audit. These are FOCUSED regression
# tests for the gates added to src.media.quality after auditing real
# production 77b5c0b1e9c344d2ac1cbca052e85b7c (Swiss Insider / sinem), which
# reached "QUALITY APPROVED" despite: content unrelated to the requested
# goal, no stored research evidence, a repeated 3-pose motion loop, and
# narration covering under a third of the final timeline. Nothing here is
# specific to that production id/topic/channel -- every fixture below is a
# synthetic, generically-named goal/topic so the gates are proven for ANY
# future YouTube worker/channel, not tuned to one incident.

FFMPEG = find_ffmpeg()


def _render(path: Path, *, width: int = 64, height: int = 64, duration: int = 1,
            audio: str = "anullsrc") -> None:
    subprocess.run([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=blue:s={width}x{height}:d={duration}",
        "-f", "lavfi", "-i", audio,
        "-shortest", "-pix_fmt", "yuv420p", str(path),
    ], check=True, timeout=20)


def _render_multi_scene(path: Path, *, width: int = 108, height: int = 192,
                         colors: tuple[str, ...] = ("black", "white", "black", "white"),
                         seg_seconds: int = 1) -> None:
    """A vertical clip with real scene changes and continuous audio -- used
    for the "a genuinely coherent production still passes" case, so
    detected-cuts/audio-presence are measured from real ffmpeg output, not
    declared."""
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error"]
    for color in colors:
        cmd += ["-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}:d={seg_seconds}"]
    n = len(colors)
    filter_complex = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seg_seconds * n}",
            "-filter_complex", filter_complex, "-map", "[v]", "-map", f"{n}:a",
            "-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(cmd, check=True, timeout=30)


def _base_evidence(**overrides) -> dict:
    base = {
        "goal": "Adventure story A", "production_backend": "repository_imagegen_storyboard_pipeline",
        "placeholder": False, "fallback": False, "production_ready": True,
        "scene_count": 6, "story_beats": ["HOOK", "SETUP", "QUEST", "ACTION", "KINDNESS", "RESOLUTION"],
        "scene_files": [f"scene-{i:02d}.png" for i in range(1, 7)],
        "scene_descriptions": ["a discovers a glowing seed", "a plants the seed",
            "a follows woodland lights", "a crosses a stream", "a helps a hedgehog",
            "a waves beside the tree"],
        "script_coverage": True, "audio_present": True, "audio_file": "narration.wav",
        "script": "Adventure story A about a glowing seed in the woods.",
        "topic": "Adventure story A", "selected_title": "Adventure story A",
        "hook": "A glowing seed appears beside an old woodland tree.",
        "ending": "A waves beside the glowing tree at dusk.",
        "story_concept": "A seed grows through patience and kindness.",
        "research_grounded": True, "research_status": "grounded",
        "duration_seconds": 4,
    }
    base.update(overrides)
    return base


def _write_sidecar(video: Path, evidence: dict) -> None:
    video.with_suffix(".quality.json").write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")


# A: research-driven production cannot become publication-ready when required
# research evidence is missing/failed.
def test_missing_research_grounding_fails_publication_readiness(tmp_path):
    video = tmp_path / "a.mp4"
    _render(video)
    _write_sidecar(video, _base_evidence(
        research_grounded=False, research_status="paid_provider_approval_pending"))
    check = validate_media_goal_artifact(video, "Adventure story A")
    assert check.gates["research_grounding"]["passed"] is False
    assert "research_grounding" in check.critical_failures
    assert check.passed is False


# B: disconnected/random scene plan fails coherence.
def test_disconnected_random_scene_sequence_fails_coherence(tmp_path):
    video = tmp_path / "b.mp4"
    _render(video)
    _write_sidecar(video, _base_evidence(scene_descriptions=["a random unrelated scene"] * 6))
    check = validate_media_goal_artifact(video, "Adventure story A")
    assert check.gates["narrative_coherence"]["passed"] is False
    assert check.passed is False


# C: excessive repeated visual assets fails or materially lowers quality.
def test_excessive_repeated_pose_loop_fails_repetition_gate(tmp_path):
    video = tmp_path / "c.mp4"
    _render(video)
    evidence = _base_evidence(
        character_motion=[{"scene_file": "scene-03.png", "pose_files": ["p1.png", "p2.png", "p3.png"],
                            "pose_fps": 4, "motion_type": "character_running_cycle",
                            "character_roi": [0.18, 0.12, 0.64, 0.82]}],
        rendered_character_motion=[{"scene_index": 2, "scene_file": "scene-03.png",
            "motion_type": "character_running_cycle", "pose_count": 3,
            "start_seconds": 20.0, "end_seconds": 30.0}],
    )
    _write_sidecar(video, evidence)
    check = validate_media_goal_artifact(video, "Adventure story A")
    assert check.gates["repetition"]["passed"] is False
    assert check.gates["repetition"]["reasons"]
    assert check.passed is False


# D: narration shorter than intended timeline fails (final spoken phrase truncated).
def test_narration_shorter_than_final_timeline_fails_av_timing(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    video = tmp_path / "d.mp4"
    _render(video, duration=6)
    narration = root / "narration.wav"
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i", "sine=d=1", str(narration)], check=True, timeout=20)
    evidence = _base_evidence(audio_file="narration.wav", source_root=str(root.resolve()), duration_seconds=6)
    _write_sidecar(video, evidence)
    check = validate_media_goal_artifact(video, "Adventure story A")
    assert check.gates["av_timing"]["applicable"] is True
    assert check.gates["av_timing"]["passed"] is False
    assert check.gates["av_timing"]["coverage_ratio"] < 0.8
    assert check.passed is False


# E: unexpected silence at the end of the final artifact is detected.
def test_unexpected_end_silence_is_detected(tmp_path):
    video = tmp_path / "e.mp4"
    subprocess.run([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=6",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-f", "lavfi", "-t", "3", "-i", "anullsrc=r=44100:cl=mono",
        "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1[aout]",
        "-map", "0:v", "-map", "[aout]", "-pix_fmt", "yuv420p", "-shortest", str(video),
    ], check=True, timeout=20)
    _write_sidecar(video, _base_evidence(duration_seconds=6))
    check = validate_media_goal_artifact(video, "Adventure story A")
    assert check.gates["audio_completeness"]["passed"] is False
    assert any("silence" in r for r in check.gates["audio_completeness"]["reasons"])
    assert check.passed is False


# F: invalid/missing final video fails closed.
def test_missing_final_video_fails_closed(tmp_path):
    check = validate_media_goal_artifact(tmp_path / "does-not-exist.mp4", "any goal")
    assert check.technical_passed is False
    assert check.gates["technical_render_validity"]["passed"] is False
    assert check.passed is False


# G: correct 9:16 output is validated (and a 16:9 output is correctly rejected).
def test_vertical_shorts_output_is_validated(tmp_path):
    vertical = tmp_path / "vertical.mp4"
    _render(vertical, width=108, height=192, duration=2)
    _write_sidecar(vertical, _base_evidence(duration_seconds=2))
    vcheck = validate_media_goal_artifact(vertical, "Adventure story A")
    assert vcheck.gates["shorts_structure"]["vertical"] is True
    assert vcheck.gates["shorts_structure"]["passed"] is True

    landscape = tmp_path / "landscape.mp4"
    _render(landscape, width=192, height=108, duration=2)
    _write_sidecar(landscape, _base_evidence(duration_seconds=2))
    lcheck = validate_media_goal_artifact(landscape, "Adventure story A")
    assert lcheck.gates["shorts_structure"]["vertical"] is False
    assert lcheck.gates["shorts_structure"]["passed"] is False
    assert any("9:16" in r for r in lcheck.gates["shorts_structure"]["reasons"])
    assert lcheck.passed is False


# H: hook/story/end structure is evaluated for Shorts.
def test_missing_hook_and_ending_fails_shorts_structure(tmp_path):
    video = tmp_path / "h.mp4"
    _render(video, width=108, height=192, duration=2)
    _write_sidecar(video, _base_evidence(
        duration_seconds=2, hook="", ending="", story_beats=["HOOK", "SETUP", "QUEST", "ACTION"]))
    check = validate_media_goal_artifact(video, "Adventure story A")
    assert check.gates["shorts_structure"]["passed"] is False
    reasons = " ".join(check.gates["shorts_structure"]["reasons"])
    assert "hook" in reasons and "payoff" in reasons


# I (visual relevance): goal unrelated to the actual generated content fails,
# proving the fix for the tautological old goal-relevance check (which
# compared the requested goal against evidence["goal"] -- a field the
# producer echoes back verbatim, so it always matched itself).
def test_goal_unrelated_to_generated_content_fails_visual_relevance(tmp_path):
    video = tmp_path / "i.mp4"
    _render(video)
    _write_sidecar(video, _base_evidence())  # script/topic/title all about "Adventure story A"
    check = validate_media_goal_artifact(video, "Completely unrelated financial market news channel")
    assert check.gates["visual_relevance"]["passed"] is False
    assert check.passed is False


# J: a genuinely coherent, fully evidence-backed production still passes ALL
# gates -- the stricter gates catch real defects without blocking a
# legitimately good production.
def test_coherent_research_grounded_production_passes_all_gates(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    video = tmp_path / "j.mp4"
    _render_multi_scene(video, width=108, height=192, seg_seconds=1)
    narration = root / "narration.wav"
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i", "sine=d=3.6", str(narration)], check=True, timeout=20)
    evidence = _base_evidence(audio_file="narration.wav", source_root=str(root.resolve()), duration_seconds=4)
    _write_sidecar(video, evidence)
    check = validate_media_goal_artifact(video, "Adventure story A")

    assert check.gates["research_grounding"]["passed"] is True
    assert check.gates["visual_relevance"]["passed"] is True
    assert check.gates["narrative_coherence"]["passed"] is True
    assert check.gates["repetition"]["passed"] is True
    assert check.gates["audio_completeness"]["passed"] is True
    assert check.gates["av_timing"]["passed"] is True
    assert check.gates["shorts_structure"]["passed"] is True
    assert check.critical_failures == ()
    assert check.passed is True


# K: round 4 repair -- quality substage evidence. Body-motion measurement
# runs one ffmpeg probe PER declared motion spec (i.e. per scene) -- the
# only quality sub-check whose worst case scales with scene count (see
# ``quality.quality_check_worst_case_seconds``). A real live mission failed
# at the flat marker "quality_check" with no finer diagnostic; this proves
# the per-scene marker is set BEFORE each blocking probe, mirroring the
# renderer's existing ``render_ffmpeg_scene_{i}_of_{n}`` convention.
def test_body_motion_check_marks_per_scene_substage_before_each_probe(monkeypatch):
    from src.media.quality import _measure_local_body_motion

    def _boom(*args, **kwargs):
        raise AssertionError("ffmpeg should not actually run in this test")

    monkeypatch.setattr(subprocess, "run", _boom)

    evidence = {"rendered_character_motion": [
        {"character_roi": [0.1, 0.1, 0.5, 0.5], "start_seconds": 0, "end_seconds": 2},
        {"character_roi": [0.1, 0.1, 0.5, 0.5], "start_seconds": 2, "end_seconds": 4},
    ]}
    sink: dict = {}
    try:
        _measure_local_body_motion(Path("unused.mp4"), evidence, "ffmpeg.exe", stage_sink=sink)
    except AssertionError:
        pass

    assert sink.get("last_stage") == "quality_body_motion_scene_1_of_2"
