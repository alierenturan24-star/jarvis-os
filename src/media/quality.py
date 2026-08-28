from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import subprocess
from pathlib import Path

# Sprint 39: MediaManager'ın LLM'den istediği bölümlerin HEPSİNİN gerçekten
# üretilip üretilmediğini kontrol eder. Yeni bir puanlama sistemi İCAT
# ETMEZ -- yalnızca beklenen bölüm başlıklarının metinde VAR olup
# olmadığına bakan, deterministik/LLM'siz bir kontrol listesidir (mevcut
# ``EvaluationEngine``/``candidate_builder`` ile AYNI ruhta: yalnızca
# ÖLÇÜLEBİLİR bir sinyale dayanır, uydurma bir kalite puanı İCAT ETMEZ).
REQUIRED_SECTIONS = (
    "SENARYO",
    "SAHNELER",
    "SESLENDİRME PLANI",
    "GÖRSEL/VİDEO PLANI",
    "ALTYAZI PLANI",
    "THUMBNAIL FİKRİ",
    "BAŞLIK",
    "AÇIKLAMA",
    "ETİKETLER",
)

MIN_WORD_COUNT = 40

# Sprint: real-production quality-gate audit (see docs/full_system_audit).
# validate_media_goal_artifact() used to collapse every check into a single
# ``passed`` boolean where the goal-relevance check compared the requested
# topic against ``evidence["goal"]`` -- a field the producer itself echoes
# back verbatim, so it always matched (tautology) no matter what content was
# actually generated. This is why a Swiss Insider goal could silently
# receive an unrelated German children's-cartoon artifact and still be
# reported "QUALITY APPROVED". These gates are ADDITIVE, deterministic (no
# LLM call, no new render/generation system) and each records its own
# evidence/reasons per Sprint requirement (auditable, not just pass/fail).
_NARRATIVE_RELEVANCE_MIN_OVERLAP = 0.15
_MOTION_UNIQUE_RATIO_FLOOR = 0.25
_MOTION_MIN_FRAMES_FOR_REPETITION_CHECK = 12
_NARRATION_COVERAGE_MIN_RATIO = 0.8
_TAIL_SILENCE_SECONDS = 3.0
_TAIL_SILENCE_DB = -50.0

# Round 4 repair (real live-mission evidence: media task failed at
# ``last_stage="quality_check"`` with no finer diagnostic, then the outer
# 75s department timeout killed it before quality_check itself finished).
# ``validate_media_goal_artifact`` runs SEVERAL independently-bounded local
# ffmpeg/ffprobe subprocess calls -- each already has its own ``timeout=``
# below, but the flat "quality_check" marker gave no visibility into which
# one was actually running when a run got slow. Named as constants (instead
# of inline literals) so ``quality_check_worst_case_seconds`` below can sum
# the SAME real numbers the subprocess calls actually use -- one source of
# truth, no risk of the budget and the calls drifting apart.
_TECHNICAL_VALIDATION_TIMEOUT_SECONDS = 15.0  # renderer.validate_video_artifact's own ffprobe probe
_SCENE_CUT_DETECTION_TIMEOUT_SECONDS = 30.0
_AUDIO_LEVEL_DETECTION_TIMEOUT_SECONDS = 30.0
_DURATION_PROBE_TIMEOUT_SECONDS = 15.0
_TAIL_SILENCE_PROBE_TIMEOUT_SECONDS = 20.0
_AUDIO_TIMING_PROBE_TIMEOUT_SECONDS = 15.0
_BODY_MOTION_PER_SCENE_TIMEOUT_SECONDS = 30.0
_SHORTS_DIMENSIONS_PROBE_TIMEOUT_SECONDS = 15.0

# Body-motion measurement runs ONE ffmpeg probe per
# ``rendered_character_motion`` entry -- i.e. per scene -- so it is the one
# sub-check whose worst case scales with scene count instead of being a
# single fixed call. Bounded here using the SAME 4-6 scene range
# ``MediaManager.plan()``'s own LLM prompt already instructs ("Metni 4-6
# sahneye böl") -- not a new, independently-invented cap.
MAX_EXPECTED_SCENES_FOR_BUDGET = 6


def quality_check_worst_case_seconds(max_scenes: int = MAX_EXPECTED_SCENES_FOR_BUDGET) -> float:
    """Real, additive worst-case wall-clock for ONE ``validate_media_goal_artifact``
    call: every bounded subprocess timeout above that this function CAN run,
    summed (not maxed) -- the sub-checks run sequentially, not in parallel,
    so a truthful outer department budget must assume each one individually
    hits its own cap. This is a static sum of already-configured timeouts
    (not a live measurement); callers (see
    ``department_orchestrator.MEDIA_DEPARTMENT_TASK_TIMEOUT_SECONDS``) use
    it to size the outer timeout FROM this real inner worst-case instead of
    guessing a number independent of it.
    """
    return (
        _TECHNICAL_VALIDATION_TIMEOUT_SECONDS
        + _SCENE_CUT_DETECTION_TIMEOUT_SECONDS
        + _AUDIO_LEVEL_DETECTION_TIMEOUT_SECONDS
        + _DURATION_PROBE_TIMEOUT_SECONDS
        + _TAIL_SILENCE_PROBE_TIMEOUT_SECONDS
        + _AUDIO_TIMING_PROBE_TIMEOUT_SECONDS
        + _SHORTS_DIMENSIONS_PROBE_TIMEOUT_SECONDS
        + max_scenes * _BODY_MOTION_PER_SCENE_TIMEOUT_SECONDS
    )


@dataclass(frozen=True)
class MediaQualityCheck:
    passed: bool
    missing_sections: tuple[str, ...]
    word_count: int
    summary: str


@dataclass(frozen=True)
class MediaArtifactQuality:
    passed: bool
    technical_passed: bool
    semantic_passed: bool
    issues: tuple[str, ...]
    scene_count: int = 0
    detected_cuts: int = 0
    max_audio_db: float | None = None
    body_motion_detected: bool = False
    body_motion_ratio: float | None = None
    # Sprint: real-production quality-gate audit -- named, evidence-carrying
    # gates (requirement: "Separate at minimum: technical render validity,
    # research grounding, narrative coherence, visual relevance, visual
    # continuity, repetition, audio completeness, AV duration/timing, Shorts
    # structure, publication readiness"). ``critical_failures`` lists the
    # gate names that MUST prevent QUALITY APPROVED/youtube_publish approval.
    gates: dict = field(default_factory=dict)
    critical_failures: tuple[str, ...] = ()


def _measure_local_body_motion(
    artifact: Path, evidence: dict, ffmpeg: str, *, stage_sink: dict | None = None,
) -> tuple[bool, float | None]:
    """Separate localized character articulation from whole-frame camera motion.

    Round 4 repair: this is the ONE quality sub-check whose real worst case
    scales with scene count (one ffmpeg probe per motion spec) -- per-scene
    ``last_stage`` markers here, matching the SAME
    ``render_ffmpeg_scene_{i}_of_{n}`` convention ``LocalVideoRenderer``
    already uses (see src/media/renderer.py), so a slow/hung run identifies
    exactly which scene's probe was running.
    """
    specs = evidence.get("rendered_character_motion", [])
    if not specs:
        return False, None
    best_ratio: float | None = None
    for index, spec in enumerate(specs):
        if stage_sink is not None:
            stage_sink["last_stage"] = f"quality_body_motion_scene_{index + 1}_of_{len(specs)}"
        roi = spec.get("character_roi")
        if not (isinstance(roi, list) and len(roi) == 4):
            continue
        start = float(spec.get("start_seconds", 0)) + .15
        duration = max(.5, min(3.0, float(spec.get("end_seconds", start + 1)) - start - .3))
        probe = subprocess.run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
            "-i", str(artifact), "-vf", "fps=8,scale=160:90,format=gray", "-f", "rawvideo", "-",
        ], capture_output=True, timeout=_BODY_MOTION_PER_SCENE_TIMEOUT_SECONDS, check=False)
        frame_size, width, height = 160 * 90, 160, 90
        frames = [probe.stdout[i:i + frame_size] for i in range(0, len(probe.stdout) - frame_size + 1, frame_size)]
        if len(frames) < 3:
            continue
        x0, y0, rw, rh = roi
        xa, xb = max(0, int(x0 * width)), min(width, int((x0 + rw) * width))
        ya, yb = max(0, int(y0 * height)), min(height, int((y0 + rh) * height))
        inside, outside = [], []
        for before, after in zip(frames, frames[1:]):
            in_sum = in_n = out_sum = out_n = 0
            for y in range(height):
                row = y * width
                for x in range(width):
                    delta = abs(after[row + x] - before[row + x])
                    if xa <= x < xb and ya <= y < yb:
                        in_sum += delta; in_n += 1
                    else:
                        out_sum += delta; out_n += 1
            inside.append(in_sum / max(in_n, 1)); outside.append(out_sum / max(out_n, 1))
        local = sum(inside) / len(inside)
        global_background = sum(outside) / len(outside)
        ratio = local / max(global_background, .25)
        best_ratio = max(best_ratio or 0.0, ratio)
        if local >= 3.0 and ratio >= 1.8:
            return True, ratio
    return False, best_ratio


def _detect_motion_repetition(evidence: dict) -> dict:
    """Flag a small fixed pose set looped for many frames as a repetitive
    slideshow rather than genuine motion diversity (requirement: "a repeated
    slideshow/pose-loop must not automatically qualify as successful motion
    generation" / "detect excessive repeated frames/assets")."""
    rendered = evidence.get("rendered_character_motion") or []
    if not rendered:
        return {"applicable": False, "severe_repetition": False, "reasons": []}
    specs_by_scene = {spec.get("scene_file"): spec for spec in evidence.get("character_motion", [])
                      if isinstance(spec, dict)}
    worst_ratio = 1.0
    detail = []
    for rendered_spec in rendered:
        scene_file = rendered_spec.get("scene_file")
        spec = specs_by_scene.get(scene_file, {})
        pose_files = spec.get("pose_files", [])
        pose_count = max(1, int(rendered_spec.get("pose_count") or len(pose_files) or 1))
        pose_fps = max(2.0, min(float(spec.get("pose_fps", 6) or 6), 12.0))
        start = float(rendered_spec.get("start_seconds", 0) or 0)
        end = float(rendered_spec.get("end_seconds", start) or start)
        total_frames = max(1, round(max(end - start, 0.0) * pose_fps))
        ratio = min(1.0, pose_count / total_frames)
        worst_ratio = min(worst_ratio, ratio)
        detail.append({"scene_file": scene_file, "pose_count": pose_count,
                        "total_frames_shown": total_frames, "unique_ratio": round(ratio, 3)})
    severe = worst_ratio < _MOTION_UNIQUE_RATIO_FLOOR and any(
        d["total_frames_shown"] >= _MOTION_MIN_FRAMES_FOR_REPETITION_CHECK for d in detail)
    reasons = []
    if severe:
        reasons.append(
            f"character motion repeats a {min(d['pose_count'] for d in detail)}-pose loop across "
            f"{max(d['total_frames_shown'] for d in detail)} frames (unique-pose ratio "
            f"{round(worst_ratio, 3)} < {_MOTION_UNIQUE_RATIO_FLOOR}); this is a still-image pose-loop, "
            "not measured motion diversity"
        )
    return {"applicable": True, "severe_repetition": severe, "worst_unique_ratio": round(worst_ratio, 3),
            "detail": detail, "reasons": reasons}


def _check_narrative_relevance(goal: str, evidence: dict) -> dict:
    """Compare the requested goal/topic against the ACTUAL generated content
    (script/scenes/title/hook/ending) -- NOT ``evidence["goal"]``, which the
    producer itself sets to the requested goal string and therefore always
    matches itself regardless of what was actually produced."""
    requested_words = {w for w in re.findall(r"\w+", (goal or "").casefold()) if len(w) >= 4}
    content_text = " ".join(str(evidence.get(key, "")) for key in
                             ("script", "topic", "selected_title", "hook", "ending", "story_concept"))
    content_text += " " + " ".join(str(d) for d in evidence.get("scene_descriptions", []))
    content_words = {w for w in re.findall(r"\w+", content_text.casefold()) if len(w) >= 4}
    overlap = (len(requested_words & content_words) / len(requested_words)) if requested_words else 1.0
    relevant = overlap >= _NARRATIVE_RELEVANCE_MIN_OVERLAP
    reasons = [] if relevant else [
        f"generated script/scenes/title share only {round(overlap * 100)}% of the requested goal's "
        "distinctive words -- content does not appear derived from the requested topic"
    ]
    return {"passed": relevant, "overlap_ratio": round(overlap, 3),
            "requested_word_count": len(requested_words), "reasons": reasons}


def _check_research_grounding(evidence: dict) -> dict:
    """A production requested as research-driven must not silently substitute
    arbitrary/default content when meaningful research failed (requirement
    1-3). ``research_grounded``/``research_evidence_ref`` are written by
    ``GeneralProductionBuilder.build()`` from the SAME ``KnowledgeBase.
    find_research()`` lookup ``MediaManager.plan()`` already performs -- no
    second research system is introduced here."""
    grounded = evidence.get("research_grounded") is True
    reasons = [] if grounded else [
        "no stored research/opportunity evidence is referenced for this topic "
        f"(research_status={evidence.get('research_status', 'unknown')!r}); content opportunity was not "
        "shown to be research-driven"
    ]
    return {"passed": grounded, "research_status": evidence.get("research_status", "unknown"),
            "evidence_ref": evidence.get("research_evidence_ref"), "reasons": reasons}


def _check_narrative_coherence(evidence: dict) -> dict:
    scene_count = int(evidence.get("scene_count", 0) or 0)
    scenes = evidence.get("scene_descriptions") or []
    beats = evidence.get("story_beats") or []
    scene_files = evidence.get("scene_files") or []
    reasons = []
    if scene_count < 4 or len(beats) < 4:
        reasons.append("insufficient meaningful scene progression")
    if evidence.get("script_coverage") is not True:
        reasons.append("script/story coverage missing")
    if scenes and len(set(str(s).strip().casefold() for s in scenes)) != len(scenes):
        reasons.append("duplicate scene descriptions indicate a disconnected/random scene sequence")
    if scenes and scene_files and len(scenes) != len(scene_files):
        reasons.append("scene descriptions do not map one-to-one onto rendered scene assets")
    return {"passed": not reasons, "scene_count": scene_count, "beat_count": len(beats), "reasons": reasons}


def _probe_duration_seconds(path: Path, ffprobe: str) -> float | None:
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=_DURATION_PROBE_TIMEOUT_SECONDS, check=False,
        )
        return float(result.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _probe_dimensions(path: Path, ffprobe: str) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
             "-of", "json", str(path)], capture_output=True, text=True,
            timeout=_SHORTS_DIMENSIONS_PROBE_TIMEOUT_SECONDS, check=False,
        )
        stream = json.loads(result.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired):
        return None


def _measure_tail_silence(artifact: Path, ffmpeg: str, overall_max_db: float | None) -> dict:
    """Detect narration/audio cutting out near the end -- a whole-file
    max_volume check passes as long as ANY part of the track has real audio,
    so it cannot see that the final seconds are silent."""
    try:
        # NOTE: no "-loglevel error" here -- volumedetect's max_volume/
        # mean_volume stats are logged at ffmpeg's default (info) level, and
        # "-loglevel error" silently discards them, making this look like a
        # missing/silent tail no matter what the audio actually contains.
        probe = subprocess.run(
            [ffmpeg, "-hide_banner", "-sseof", f"-{_TAIL_SILENCE_SECONDS:.2f}",
             "-i", str(artifact), "-af", "volumedetect", "-f", "null", "NUL"],
            capture_output=True, text=True, timeout=_TAIL_SILENCE_PROBE_TIMEOUT_SECONDS, check=False,
        )
        match = re.search(r"max_volume:\s*(-?[\d.]+) dB", probe.stderr)
        tail_db = float(match.group(1)) if match else None
    except (OSError, subprocess.TimeoutExpired):
        tail_db = None
    # No volumedetect stats at all for the tail window (empty/near-empty audio
    # stream in that range) is itself evidence of missing tail audio.
    silent = overall_max_db is not None and overall_max_db > _TAIL_SILENCE_DB and (
        tail_db is None or tail_db <= _TAIL_SILENCE_DB)
    return {"tail_max_db": tail_db, "unexpected_end_silence": silent}


def _check_audio_timing(evidence: dict, artifact: Path, artifact_duration: float | None,
                         source_root: Path | None, ffprobe: str | None) -> dict:
    """Validate narration duration against the final timeline duration
    (requirement 20-26): the final spoken phrase must not be truncated and
    scene/AV duration should reflect real narration coverage, not just an
    arbitrarily assembled fixed clip length."""
    audio_name = evidence.get("audio_file")
    if not (audio_name and source_root and ffprobe and artifact_duration):
        return {"passed": True, "applicable": False, "reasons": []}
    narration_path = source_root / str(audio_name)
    if not narration_path.is_file():
        return {"passed": False, "applicable": True,
                "reasons": ["declared narration source file is missing"]}
    narration_seconds = _probe_duration_seconds(narration_path, ffprobe)
    if narration_seconds is None:
        return {"passed": False, "applicable": True, "reasons": ["narration duration could not be measured"]}
    coverage = narration_seconds / artifact_duration if artifact_duration else 0.0
    reasons = []
    if coverage < _NARRATION_COVERAGE_MIN_RATIO:
        reasons.append(
            f"narration covers only {round(coverage * 100)}% of the {round(artifact_duration)}s final "
            f"timeline ({round(narration_seconds, 1)}s of narration) -- the final spoken phrase and "
            "remaining timeline are effectively unnarrated/truncated"
        )
    return {"passed": not reasons, "applicable": True, "narration_seconds": round(narration_seconds, 2),
            "artifact_seconds": round(artifact_duration, 2), "coverage_ratio": round(coverage, 3),
            "reasons": reasons}


def _check_shorts_structure(evidence: dict, artifact: Path, ffprobe: str | None) -> dict:
    is_short = (
        str(evidence.get("video_type", "")).casefold() in {"short", "shorts", "youtube_short"}
        or evidence.get("content_type") == "SHORT"
        or float(evidence.get("duration_seconds", 0) or 0) <= 180
    )
    if not is_short:
        return {"is_short": False, "passed": True, "reasons": []}
    dims = _probe_dimensions(artifact, ffprobe) if ffprobe else None
    vertical = bool(dims and dims[1] > dims[0] and 0.5 <= (dims[0] / dims[1]) <= 0.63)
    hook_present = bool(str(evidence.get("hook", "")).strip())
    ending_present = bool(str(evidence.get("ending", "")).strip())
    beats = evidence.get("story_beats") or []
    resolution_beat = bool(beats) and any(str(b).upper() in {"RESOLUTION", "ENDING", "PAYOFF"} for b in beats)
    reasons = []
    if dims is not None and not vertical:
        reasons.append(f"expected vertical 9:16 Shorts output, measured {dims[0]}x{dims[1]}")
    elif dims is None:
        reasons.append("could not measure output dimensions to validate vertical 9:16 Shorts format")
    if not hook_present:
        reasons.append("no declared opening hook for the first seconds of the Short")
    if not (ending_present and resolution_beat):
        reasons.append("no declared resolution/ending payoff -- video must not just stop at duration")
    return {"is_short": True, "dimensions": dims, "vertical": vertical, "hook_present": hook_present,
            "ending_present": ending_present, "resolution_beat": resolution_beat, "reasons": reasons,
            "passed": not reasons}


def check_media_plan_quality(plan_text: str) -> MediaQualityCheck:
    """``plan_text`` (MediaManager'ın TEK LLM çağrısından dönen ham metin)
    beklenen tüm bölümleri içeriyor mu ve makul uzunlukta mı? Bir LLM
    çağrısı YAPMAZ, yeni bir ölçüm İCAT ETMEZ."""

    text = plan_text or ""
    missing = tuple(section for section in REQUIRED_SECTIONS if section not in text)
    word_count = len(text.split())

    issues: list[str] = []
    if missing:
        issues.append(f"Eksik bölüm(ler): {', '.join(missing)}")
    if word_count < MIN_WORD_COUNT:
        issues.append(f"Metin çok kısa ({word_count} kelime, beklenen en az {MIN_WORD_COUNT}).")

    passed = not issues
    summary = (
        "Tüm beklenen bölümler mevcut, içerik yeterli uzunlukta."
        if passed
        else "; ".join(issues)
    )

    return MediaQualityCheck(
        passed=passed,
        missing_sections=missing,
        word_count=word_count,
        summary=summary,
    )


def validate_media_goal_artifact(
    path: str | Path, goal: str = "", *, stage_sink: dict | None = None,
) -> MediaArtifactQuality:
    """Validate container integrity separately from production semantics.

    Semantic acceptance requires explicit provenance, multiple authored story
    scenes, script coverage, audible audio, and measured temporal changes.
    Unknown, fallback, placeholder, and test artifacts fail closed.

    Sprint (real-production quality-gate audit): semantic acceptance now also
    requires evidence-backed research grounding, non-tautological goal
    relevance, non-repetitive motion, full-timeline audio coverage, and (for
    Shorts) a validated vertical/hook/payoff structure -- see the module
    docstring and ``MediaArtifactQuality.gates``/``critical_failures``.

    Round 4 repair: ``stage_sink`` (the SAME shared dict ``MediaManager``/
    ``LocalVideoRenderer`` already write ``last_stage`` markers into, see
    src/media/manager.py and src/media/renderer.py) gets a marker before
    every potentially-blocking local ffmpeg/ffprobe subprocess call below,
    so a slow/timed-out quality_check identifies exactly which sub-check
    was running instead of the previous flat "quality_check" marker.
    """
    from src.media.renderer import find_ffmpeg, find_ffprobe, validate_video_artifact

    if stage_sink is not None:
        stage_sink["last_stage"] = "quality_technical_validation"
    artifact = Path(path)
    technical = validate_video_artifact(artifact)
    issues: list[str] = []
    gates: dict[str, dict] = {"technical_render_validity": {"passed": technical, "reasons": [] if technical else
                              ["technical artifact validation failed"]}}
    if not technical:
        issues.append("technical artifact validation failed")
        if stage_sink is not None:
            stage_sink["last_stage"] = "quality_complete"
        return MediaArtifactQuality(False, False, False, tuple(issues), gates=gates,
                                     critical_failures=("technical_render_validity",))

    sidecar = artifact.with_suffix(".quality.json")
    try:
        evidence = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        evidence = {}
        issues.append("production quality provenance missing")

    forbidden = {"placeholder", "test", "fallback", "deterministic_scene_card"}
    backend = str(evidence.get("production_backend", "")).casefold()
    provenance_reasons = []
    if evidence.get("production_ready") is not True:
        provenance_reasons.append("artifact is not declared production-ready")
    if evidence.get("placeholder") is not False or evidence.get("fallback") is not False:
        provenance_reasons.append("placeholder/fallback artifact")
    if any(marker in backend for marker in forbidden):
        provenance_reasons.append("non-production renderer provenance")
    if "production quality provenance missing" in issues:
        provenance_reasons.append("production quality provenance missing")
    issues.extend(reason for reason in provenance_reasons if reason not in issues)
    gates["technical_render_validity"]["reasons"] = list(gates["technical_render_validity"]["reasons"]) + \
        [r for r in provenance_reasons if r not in gates["technical_render_validity"]["reasons"]]
    gates["technical_render_validity"]["passed"] = gates["technical_render_validity"]["passed"] and not provenance_reasons

    if stage_sink is not None:
        stage_sink["last_stage"] = "quality_semantic_validation"
    coherence = _check_narrative_coherence(evidence)
    scene_count = coherence["scene_count"]
    gates["narrative_coherence"] = coherence
    issues.extend(r for r in coherence["reasons"] if r not in issues)

    relevance = _check_narrative_relevance(goal, evidence)
    gates["visual_relevance"] = relevance
    issues.extend(r for r in relevance["reasons"] if r not in issues)

    if stage_sink is not None:
        stage_sink["last_stage"] = "quality_research_grounding"
    research = _check_research_grounding(evidence)
    gates["research_grounding"] = research
    issues.extend(r for r in research["reasons"] if r not in issues)

    detected_cuts = 0
    max_audio_db: float | None = None
    artifact_duration: float | None = None
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if ffmpeg:
        if stage_sink is not None:
            stage_sink["last_stage"] = "quality_scene_cut_detection"
        scene_probe = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(artifact), "-filter:v", "select=gt(scene\\,0.25),showinfo", "-f", "null", "NUL"],
            capture_output=True, text=True, timeout=_SCENE_CUT_DETECTION_TIMEOUT_SECONDS, check=False,
        )
        detected_cuts = len(re.findall(r"pts_time:", scene_probe.stderr))
        if stage_sink is not None:
            stage_sink["last_stage"] = "quality_audio_level_detection"
        audio_probe = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(artifact), "-af", "volumedetect", "-f", "null", "NUL"],
            capture_output=True, text=True, timeout=_AUDIO_LEVEL_DETECTION_TIMEOUT_SECONDS, check=False,
        )
        match = re.search(r"max_volume:\s*(-?[\d.]+) dB", audio_probe.stderr)
        if match:
            max_audio_db = float(match.group(1))
    if ffprobe:
        if stage_sink is not None:
            stage_sink["last_stage"] = "quality_duration_probe"
        artifact_duration = _probe_duration_seconds(artifact, ffprobe)
    if detected_cuts < 3:
        issues.append("measured temporal/scene variation is insufficient")

    audio_reasons = []
    if evidence.get("audio_present") is not True or max_audio_db is None or max_audio_db <= -60:
        audio_reasons.append("meaningful voice/audio is absent")
    if stage_sink is not None:
        stage_sink["last_stage"] = "quality_tail_silence_detection"
    tail = _measure_tail_silence(artifact, ffmpeg, max_audio_db) if ffmpeg else {"unexpected_end_silence": False, "tail_max_db": None}
    if tail["unexpected_end_silence"]:
        audio_reasons.append(
            f"unexpected silence detected in the final {_TAIL_SILENCE_SECONDS:.0f}s of the artifact "
            "while the track overall has real audio -- narration/audio cuts out before the end"
        )
    gates["audio_completeness"] = {"passed": not audio_reasons, "max_audio_db": max_audio_db,
                                    "tail_max_db": tail["tail_max_db"], "reasons": audio_reasons}
    issues.extend(r for r in audio_reasons if r not in issues)

    source_root_raw = evidence.get("source_root")
    source_root = Path(source_root_raw) if source_root_raw else None
    if stage_sink is not None:
        stage_sink["last_stage"] = "quality_audio_timing_validation"
    timing = _check_audio_timing(evidence, artifact, artifact_duration, source_root, ffprobe)
    gates["av_timing"] = timing
    issues.extend(r for r in timing["reasons"] if r not in issues)

    if stage_sink is not None:
        stage_sink["last_stage"] = "quality_body_motion_detection"
    body_motion_detected, body_motion_ratio = (
        _measure_local_body_motion(artifact, evidence, ffmpeg, stage_sink=stage_sink) if ffmpeg else (False, None)
    )
    if evidence.get("rendered_character_motion") and not body_motion_detected:
        issues.append("declared character motion is camera/global motion only")

    if stage_sink is not None:
        stage_sink["last_stage"] = "quality_motion_repetition_check"
    repetition = _detect_motion_repetition(evidence)
    gates["repetition"] = {"passed": not repetition["severe_repetition"], "reasons": repetition["reasons"],
                            "worst_unique_ratio": repetition.get("worst_unique_ratio")}
    issues.extend(r for r in repetition["reasons"] if r not in issues)

    identity = evidence.get("character_identity")
    continuity_reasons = []
    if evidence.get("rendered_character_motion") and not (isinstance(identity, dict) and identity.get("name")):
        continuity_reasons.append("recurring character identity missing for a motion-bearing production")
    gates["visual_continuity"] = {"passed": not continuity_reasons, "reasons": continuity_reasons}
    issues.extend(r for r in continuity_reasons if r not in issues)

    if stage_sink is not None:
        stage_sink["last_stage"] = "quality_shorts_structure_validation"
    shorts = _check_shorts_structure(evidence, artifact, ffprobe)
    gates["shorts_structure"] = shorts
    issues.extend(r for r in shorts["reasons"] if r not in issues)

    semantic = not issues
    critical_failures = tuple(name for name, gate in gates.items() if not gate.get("passed", True))
    gates["publication_readiness"] = {"passed": technical and semantic and not critical_failures,
                                      "reasons": list(issues)}
    if not gates["publication_readiness"]["passed"]:
        critical_failures = critical_failures + ("publication_readiness",) if "publication_readiness" not in critical_failures else critical_failures

    if stage_sink is not None:
        stage_sink["last_stage"] = "quality_complete"
    return MediaArtifactQuality(technical and semantic, technical, semantic, tuple(issues), scene_count,
                                 detected_cuts, max_audio_db, body_motion_detected, body_motion_ratio,
                                 gates=gates, critical_failures=critical_failures)
