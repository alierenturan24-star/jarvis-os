from __future__ import annotations

import base64
import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


# Sprint: real-production quality-gate audit -- the production package this
# renderer composes is declared/approved as a YouTube "SHORT" (see
# workforce/manager.py's publication_metadata), which YouTube requires as
# vertical 9:16. The renderer previously always targeted 1280x720 (16:9
# landscape) regardless of that declaration, which the quality gate had no
# way to catch (see src.media.quality._check_shorts_structure). Render
# target updated to true vertical; this does not change scene/pose/audio
# generation, only the output frame the same assets are composited into.
VERTICAL_WIDTH, VERTICAL_HEIGHT = 1080, 1920


@dataclass(frozen=True)
class RenderResult:
    success: bool
    artifact_path: str = ""
    error: str = ""
    ffmpeg_path: str = ""
    audio_used: bool = False
    production_ready: bool = False
    quality_manifest_path: str = ""


def _motion_spec_for_scene(manifest: dict, scene_name: str) -> dict | None:
    """Return an authored pose-sequence declaration for one scene, if present."""
    for spec in manifest.get("character_motion", []):
        if spec.get("scene_file") == scene_name and len(spec.get("pose_files", [])) >= 2:
            return spec
    return None


def find_ffmpeg() -> str | None:
    """Return an existing encoder without downloading or installing anything."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    local = Path("tools/ffmpeg/bin/ffmpeg.exe").resolve()
    return str(local) if local.is_file() else None


def find_ffprobe() -> str | None:
    system = shutil.which("ffprobe")
    if system:
        return system
    local = Path("tools/ffmpeg/bin/ffprobe.exe").resolve()
    return str(local) if local.is_file() else None


class LocalVideoRenderer:
    """Small deterministic producer that composes real MP4s with FFmpeg.

    Scene cards are generated with the Python standard library.  This keeps
    acquisition explicit: the only external production dependency is an
    already-installed FFmpeg executable.  Nothing is downloaded or published.
    """

    def __init__(self, output_root: str | Path = "workspace/artifacts/media") -> None:
        self.output_root = Path(output_root)

    @property
    def available(self) -> bool:
        return find_ffmpeg() is not None

    def render(
        self, topic: str, narration: str, duration_seconds: int = 60,
        *, stage_sink: dict | None = None,
    ) -> RenderResult:
        # Mission repair (real "Jarvis İsviçre için video üret." failure,
        # FIX 5): a real render timeout only ever showed the single coarse
        # marker "render" -- this whole method can run several REAL
        # ffmpeg subprocess calls in sequence (one per scene, plus a final
        # composition pass), each individually bounded (see below) but
        # with no visibility into which one was actually running. Finer
        # markers are written into the SAME shared ``stage_sink`` dict
        # used elsewhere (see ``report_builder._task_note``) -- no new
        # renderer, no change to the existing per-subprocess timeouts.
        if stage_sink is not None:
            stage_sink["last_stage"] = "render_prepare"
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return RenderResult(
                False,
                error=(
                    "FFmpeg bulunamadı. Gerçek MP4 üretimi çalıştırılmadı; "
                    "kurulum veya workspace-local güvenli binary için kullanıcı onayı gerekiyor."
                ),
            )

        package = _find_production_package(topic)
        if package is None:
            return RenderResult(
                False,
                error=(
                    "Production media capability eksik: yalnız FFmpeg ve placeholder/test "
                    "scene-card renderer mevcut. Generative scene assets, gerçek anlatım "
                    "ve production provenance olmadan artifact kabul edilmedi."
                ),
                ffmpeg_path=ffmpeg,
            )
        return self._render_production_package(package, topic, duration_seconds, ffmpeg, stage_sink=stage_sink)

    def _render_production_package(
        self, package: Path, topic: str, duration_seconds: int, ffmpeg: str,
        *, stage_sink: dict | None = None,
    ) -> RenderResult:
        try:
            manifest = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            return RenderResult(False, error=f"Production manifest okunamadı: {error}", ffmpeg_path=ffmpeg)

        root = package.parent
        scenes = [root / name for name in manifest.get("scene_files", [])]
        audio = root / str(manifest.get("audio_file", ""))
        if (
            manifest.get("placeholder") is not False
            or manifest.get("fallback") is not False
            or len(scenes) < 4
            or not all(path.is_file() and path.stat().st_size > 10_000 for path in scenes)
            or not audio.is_file()
        ):
            return RenderResult(False, error="Production package kalite/provenance ön koşullarını sağlamıyor.", ffmpeg_path=ffmpeg)

        safe_name = _safe_name(topic)
        job_dir = self.output_root / safe_name
        job_dir.mkdir(parents=True, exist_ok=True)
        output_path = job_dir / f"{safe_name}-production.mp4"
        # Sprint: real-production quality-gate audit -- duration used to come
        # entirely from the caller's fixed ``duration_seconds`` parameter,
        # independent of how long the real narration/scene plan actually is
        # (the known defect: narration ending ~20s into a 60s video, leaving
        # a long silent tail). Total duration now follows the real measured
        # narration length when available, and each scene's own share of
        # that duration follows its authored ``scene_plan`` timing rather
        # than an even split.
        total_duration = float(manifest.get("narration_seconds") or 0) or float(max(duration_seconds, 1))
        scene_plan = manifest.get("scene_plan") or []
        if len(scene_plan) == len(scenes):
            raw = [max(0.5, float(item.get("duration_seconds", 0) or 0)) for item in scene_plan]
            raw_total = sum(raw) or total_duration
            segment_durations = [value * (total_duration / raw_total) for value in raw]
        else:
            segment_durations = [total_duration / len(scenes)] * len(scenes)
        segment_paths: list[Path] = []
        rendered_motion: list[dict] = []
        for index, scene in enumerate(scenes):
            if stage_sink is not None:
                stage_sink["last_stage"] = f"render_ffmpeg_scene_{index + 1}_of_{len(scenes)}"
            segment_seconds = segment_durations[index]
            segment = job_dir / f"production-scene-{index + 1:02d}.mp4"
            motion = _motion_spec_for_scene(manifest, scene.name)
            if motion:
                poses = [root / name for name in motion["pose_files"]]
                if not all(path.is_file() and path.stat().st_size > 10_000 for path in poses):
                    return RenderResult(False, error="Character motion pose asset eksik/gecersiz.", ffmpeg_path=ffmpeg)
                pose_seconds = 1.0 / max(2.0, min(float(motion.get("pose_fps", 6)), 12.0))
                frame_count = math.ceil(segment_seconds / pose_seconds)
                sequence = job_dir / f"motion-scene-{index + 1:02d}.txt"
                lines = []
                for frame_index in range(frame_count):
                    pose = poses[frame_index % len(poses)]
                    lines.extend((f"file '{pose.resolve().as_posix()}'\n", f"duration {pose_seconds:.5f}\n"))
                lines.append(f"file '{poses[(frame_count - 1) % len(poses)].resolve().as_posix()}'\n")
                sequence.write_text("".join(lines), encoding="utf-8")
                command = [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(sequence),
                    "-vf", f"scale={VERTICAL_WIDTH}:{VERTICAL_HEIGHT}:force_original_aspect_ratio=increase,"
                           f"crop={VERTICAL_WIDTH}:{VERTICAL_HEIGHT},fps=25,format=yuv420p",
                    "-t", f"{segment_seconds:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", str(segment),
                ]
                rendered_motion.append({
                    "scene_index": index, "scene_file": scene.name,
                    "motion_type": str(motion.get("motion_type", "character_locomotion")),
                    "character_roi": motion.get("character_roi"),
                    "start_seconds": sum(segment_durations[:index]),
                    "end_seconds": sum(segment_durations[:index + 1]),
                    "pose_count": len(poses),
                })
            elif scene.suffix.casefold() == ".mp4":
                # Sprint: multi-provider media capability foundation --
                # image_to_video pipeline integration. A scene file is
                # already a real generated video (see
                # GeneralProductionBuilder._maybe_generate_scene_motion,
                # enable_scene_motion) -- scale/crop/trim it directly
                # instead of animating a still with zoompan. Audio is
                # stripped here too (-an); the final composition step below
                # applies the single narration track over every segment.
                command = [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(scene),
                    "-vf", f"scale={VERTICAL_WIDTH}:{VERTICAL_HEIGHT}:force_original_aspect_ratio=increase,"
                           f"crop={VERTICAL_WIDTH}:{VERTICAL_HEIGHT},fps=25,format=yuv420p",
                    "-t", f"{segment_seconds:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", str(segment),
                ]
            else:
                frames = max(1, round(segment_seconds * 25))
                zoom = "min(zoom+0.00045,1.08)" if index % 2 == 0 else "if(lte(zoom,1.0),1.08,max(1.0,zoom-0.00045))"
                pre_w, pre_h = VERTICAL_WIDTH + 120, VERTICAL_HEIGHT + 68
                command = [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-i", str(scene),
                    "-vf", f"scale={pre_w}:{pre_h}:force_original_aspect_ratio=increase,crop={pre_w}:{pre_h},"
                           f"zoompan=z='{zoom}':d={frames}:s={VERTICAL_WIDTH}x{VERTICAL_HEIGHT}:fps=25,format=yuv420p",
                    "-t", f"{segment_seconds:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", str(segment),
                ]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
            if completed.returncode != 0:
                return RenderResult(False, error=f"Production scene render başarısız: {completed.stderr[-400:]}", ffmpeg_path=ffmpeg)
            segment_paths.append(segment)

        concat = job_dir / "production-scenes.txt"
        concat.write_text("".join(f"file '{path.name}'\n" for path in segment_paths), encoding="utf-8")
        command = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", concat.name,
            "-i", str(audio.resolve()), "-t", str(max(total_duration, 1)), "-c:v", "copy",
            "-af", "atempo=1.07,loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", output_path.name,
        ]
        if stage_sink is not None:
            stage_sink["last_stage"] = "render_ffmpeg_compose"
        completed = subprocess.run(command, cwd=job_dir, capture_output=True, text=True, timeout=180, check=False)
        if completed.returncode != 0:
            return RenderResult(False, error=f"Production composition başarısız: {completed.stderr[-400:]}", ffmpeg_path=ffmpeg)

        if stage_sink is not None:
            stage_sink["last_stage"] = "render_validate"
        if not validate_video_artifact(output_path):
            return RenderResult(False, error="Production composition başarısız: artifact doğrulaması geçmedi.", ffmpeg_path=ffmpeg)

        quality_manifest = output_path.with_suffix(".quality.json")
        evidence = dict(manifest)
        evidence.update({
            "artifact_path": str(output_path.resolve()),
            "scene_count": len(scenes),
            "duration_seconds": max(total_duration, 1),
            "audio_present": True,
            "script_coverage": len(manifest.get("story_beats", [])) == len(scenes),
            "production_ready": True,
            "rendered_character_motion": rendered_motion,
            # Sprint: real-production quality-gate audit -- lets
            # validate_media_goal_artifact() locate the original narration
            # source file (audio_file is just a filename) to cross-check its
            # real duration against the final artifact's timeline.
            "source_root": str(root.resolve()),
        })
        quality_manifest.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        return RenderResult(
            True, str(output_path.resolve()), ffmpeg_path=ffmpeg, audio_used=True,
            production_ready=True, quality_manifest_path=str(quality_manifest.resolve()),
        )


def validate_video_artifact(path: str | Path) -> bool:
    candidate = Path(path)
    try:
        if not candidate.is_file() or candidate.stat().st_size < 1024:
            return False
        with candidate.open("rb") as handle:
            header = handle.read(64)
        if candidate.suffix.casefold() == ".mp4" and b"ftyp" not in header:
            return False
    except OSError:
        return False

    ffprobe = find_ffprobe()
    if not ffprobe:
        return True
    try:
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type",
             "-of", "default=nw=1:nk=1", str(candidate)],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0 and "video" in probe.stdout.casefold()


def _find_production_package(topic: str, asset_root: str | Path = "workspace/assets/media") -> Path | None:
    """Select a declared production package by generic goal-token overlap."""
    requested = {word for word in re.findall(r"\w+", topic.casefold()) if len(word) >= 4}
    best: tuple[float, Path] | None = None
    for manifest_path in Path(asset_root).rglob("production.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        declared = {word for word in re.findall(r"\w+", str(manifest.get("goal", "")).casefold()) if len(word) >= 4}
        score = len(requested & declared) / max(len(requested), 1)
        if score >= 0.6 and (best is None or score > best[0]
                              or (score == best[0] and manifest_path.stat().st_mtime > best[1].stat().st_mtime)):
            best = (score, manifest_path)
    return best[1] if best else None


def has_production_media_capability(topic: str) -> bool:
    """Whether a goal-matching, non-placeholder production package exists."""
    package = _find_production_package(topic)
    if package is None:
        source_root = Path("workspace/assets/media/channel-default-sources")
        paired_source = any(
            (source_root / f"{story.name.removesuffix('-storyboard.png')}-running-poses.png").is_file()
            for story in source_root.glob("*-storyboard.png")
        )
        return bool(find_ffmpeg() and paired_source and (shutil.which("edge-tts") or shutil.which("powershell.exe")))
    if find_ffmpeg() is None:
        return False
    try:
        manifest = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        manifest.get("placeholder") is False
        and manifest.get("fallback") is False
        and len(manifest.get("scene_files", [])) >= 4
        and bool(manifest.get("audio_file"))
    )


def find_goal_production_package(topic: str) -> Path | None:
    """Public package lookup for the pre-render builder/router."""
    return _find_production_package(topic)


def _safe_name(value: str) -> str:
    folded = "".join(char.lower() if char.isalnum() else "-" for char in value.strip())
    compact = "-".join(part for part in folded.split("-") if part)
    return (compact[:72] or "jarvis-video")


def _write_sapi_wav(path: Path, narration: str) -> bool:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell or not narration.strip():
        return False
    escaped_path = str(path.resolve()).replace("'", "''")
    escaped_text = " ".join(narration.split())[:4000].replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{escaped_path}'); "
        f"$s.Speak('{escaped_text}'); $s.Dispose()"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        completed = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    try:
        return completed.returncode == 0 and path.is_file() and path.stat().st_size > 1024
    except OSError:
        return False


