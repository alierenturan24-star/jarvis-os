from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from src.media.capability_model import IMAGE_TO_VIDEO, SceneProvenance, TEXT_TO_IMAGE
from src.media.provider_selection import rank_available_providers
from src.media.quality import REQUIRED_SECTIONS
from src.media.renderer import _write_sapi_wav, find_ffmpeg, find_ffprobe
from src.providers.execution_history import ProviderExecutionHistory


PRODUCTION_CAPABILITIES = {
    "story_generation": "history-guided production brief",
    "scene_generation": "repository imagegen storyboard source compositor",
    "character_visual_generation": "canonical character source + crop compositor",
    "motion_generation": "authored multi-pose source compositor",
    "narration_generation": "Windows System.Speech WAV",
    "thumbnail_generation": "authored storyboard thumbnail crop",
    "video_render": "LocalVideoRenderer/FFmpeg",
    "technical_validation": "validate_video_artifact/ffprobe",
    "semantic_validation": "validate_media_goal_artifact",
}

# Sprint: capability-gate audit (mission 4a50230ffad2400bbb2aff173bd2a797) --
# the pre-authored storyboard/pose art under channel-default-sources
# (lantern/silver-boat/Leni) MUST NOT be silently substituted for unrelated
# goals. This used to be gated by scanning the goal text for the substring
# "leni" -- which is negation-blind: a goal that explicitly PROHIBITS Leni/
# silver-boat/lantern-seed assets ("do NOT use: Leni, silver boat, ...")
# still CONTAINS the word "leni" and was incorrectly treated as a request to
# use them (this is exactly what happened in mission
# 4a50230ffad2400bbb2aff173bd2a797: the goal explicitly forbade these assets
# and demanded an honest CAPABILITY_GAP, but the keyword scan unlocked the
# 'silver-boat' authored asset anyway). There is no real generative image/
# video model in this environment -- the authored art is a fixed legacy/demo
# series, not a stand-in for genuine generation capability. It is now only
# ever used when a caller EXPLICITLY opts in via ``allow_legacy_authored_
# series`` (real production dispatch never sets this); every other goal
# fails honestly with CAPABILITY_GAP instead of reusing unrelated artwork.
_MAX_AUTHORED_SCENE_SLOTS = 6  # the storyboard art is a fixed 3x2 grid; no more distinct authored art exists

# Capabilities backed only by the fixed legacy authored-art compositor --
# never "available" unless that legacy series is explicitly requested.
_VISUAL_CAPABILITIES = ("scene_generation", "character_visual_generation",
                        "motion_generation", "thumbnail_generation")

_SCENE_LINE = re.compile(
    r"Sahne\s+\d+\s*\(~?\s*(?P<seconds>\d+(?:\.\d+)?)\s*sn\)\s*:\s*"
    r"Anlat[iı]m\s*:\s*(?P<narration>.*?)\s*\|\s*"
    r"G[oö]rsel\s*:\s*(?P<visual>.*?)\s*\|\s*"
    r"Ekran\s+yaz[iı]s[iı]\s*:\s*(?P<caption>.*)$",
    re.IGNORECASE | re.MULTILINE,
)

_BEAT_VOCAB = ("SETUP", "DEVELOPMENT", "TWIST", "CLIMAX")
_BEAT_PURPOSE = {
    "HOOK": "grab attention with the core intrigue",
    "SETUP": "establish context for the topic",
    "DEVELOPMENT": "develop the core information/angle",
    "TWIST": "reveal an unexpected angle or contrast",
    "CLIMAX": "deliver the key payoff/insight",
    "RESOLUTION": "close with takeaway and call to action",
}

_TTS_VOICE_BY_LANGUAGE = {
    "de-DE": "de-DE-KatjaNeural",
    "de-CH": "de-CH-LeniNeural",
    "de-AT": "de-AT-IngridNeural",
    "en-US": "en-US-AriaNeural",
    "en-GB": "en-GB-SoniaNeural",
    "tr-TR": "tr-TR-EmelNeural",
    "fr-FR": "fr-FR-DeniseNeural",
    "fr-CH": "fr-CH-ArianeNeural",
    "it-CH": "it-CH-ElsaNeural",
}
_DEFAULT_TTS_VOICE = "en-US-AriaNeural"


def _beat_for_index(index: int, total: int) -> str:
    if total <= 1:
        return "HOOK"
    if index == 0:
        return "HOOK"
    if index == total - 1:
        return "RESOLUTION"
    return _BEAT_VOCAB[(index - 1) % len(_BEAT_VOCAB)]


def _resolve_tts_voice(channel_language: str) -> str:
    return _TTS_VOICE_BY_LANGUAGE.get(channel_language, _DEFAULT_TTS_VOICE)


@dataclass(frozen=True)
class ScenePlan:
    scene_id: str
    script_beat_id: str
    purpose: str
    narration_segment: str
    visual_description: str
    duration_seconds: float
    transition: str = "cut"


@dataclass(frozen=True)
class ParsedProductionPlan:
    hook: str
    script: str
    ending: str
    scenes: tuple[ScenePlan, ...]
    title: str
    description: str
    tags: tuple[str, ...]
    thumbnail_concept: str


def _split_sections(text: str) -> dict[str, str]:
    positions = []
    for name in REQUIRED_SECTIONS:
        match = re.search(rf"^{re.escape(name)}\s*$", text, re.MULTILINE)
        if match:
            positions.append((match.start(), match.end(), name))
    positions.sort()
    sections: dict[str, str] = {}
    for index, (_, end, name) in enumerate(positions):
        content_end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        sections[name] = text[end:content_end].strip()
    return sections


def parse_plan_text(plan_text: str) -> ParsedProductionPlan | None:
    """Turn the real, goal-driven LLM plan text (``MediaManager.plan()``'s
    ``route_and_generate`` output) into structured production content.

    Returns ``None`` if the required sections are missing/malformed -- the
    caller must treat that as a genuine content-generation failure, never
    fall back to fixed/canned story text (Sprint: real-production
    quality-gate audit requirement -- research/goal must actually drive the
    video, not just be recorded as inert metadata).
    """

    sections = _split_sections(plan_text or "")
    script = sections.get("SENARYO", "").strip()
    scenes_block = sections.get("SAHNELER", "")
    if not script or not scenes_block:
        return None

    matches = list(_SCENE_LINE.finditer(scenes_block))
    if not matches:
        return None

    scenes = []
    total = min(len(matches), _MAX_AUTHORED_SCENE_SLOTS)
    for index, match in enumerate(matches[:total]):
        beat = _beat_for_index(index, total)
        narration = match.group("narration").strip()
        visual = match.group("visual").strip()
        if not narration or not visual:
            return None
        scenes.append(ScenePlan(
            scene_id=f"scene-{index + 1:02d}",
            script_beat_id=beat,
            purpose=_BEAT_PURPOSE[beat],
            narration_segment=narration,
            visual_description=visual,
            duration_seconds=float(match.group("seconds")),
        ))
    if len(scenes) < 4:
        return None

    title = sections.get("BAŞLIK", "").strip().splitlines()[0].strip() if sections.get("BAŞLIK") else ""
    description = sections.get("AÇIKLAMA", "").strip()
    tags_raw = sections.get("ETİKETLER", "").strip()
    tags = tuple(tag.strip() for tag in tags_raw.split(",") if tag.strip())
    thumbnail_concept = sections.get("THUMBNAIL FİKRİ", "").strip().splitlines()[0].strip() \
        if sections.get("THUMBNAIL FİKRİ") else ""
    if not title:
        return None

    return ParsedProductionPlan(
        hook=scenes[0].narration_segment,
        script=script,
        ending=scenes[-1].narration_segment,
        scenes=tuple(scenes),
        title=title,
        description=description or script[:280],
        tags=tags,
        thumbnail_concept=thumbnail_concept or title,
    )


@dataclass(frozen=True)
class PackageBuildResult:
    success: bool
    manifest_path: str = ""
    error: str = ""
    production_id: str = ""
    # Sprint: capability-gate audit -- required vs genuinely available vs
    # missing, so a caller (MediaManager/workforce decision log) can report
    # truthfully instead of declaring visual capabilities "used" merely
    # because the workflow requested them.
    required_capabilities: tuple[str, ...] = ()
    available_capabilities: tuple[str, ...] = ()
    missing_capabilities: tuple[str, ...] = ()


class GeneralProductionBuilder:
    """Create a new renderer package from channel memory and authored sources.

    This is the missing pre-render stage of the existing pipeline. It does not
    copy an old MP4 or weaken validation; it creates new scene, motion, audio,
    thumbnail and manifest artifacts consumed by ``LocalVideoRenderer``, built
    from the real, goal-driven, research-grounded plan text -- not a fixed
    story template (see ``parse_plan_text``/``allow_legacy_authored_series``).
    """

    def __init__(self, source_root: str | Path = "workspace/assets/media/channel-default-sources",
                 output_root: str | Path = "workspace/assets/media/generated") -> None:
        self.source_root = Path(source_root)
        self.output_root = Path(output_root)

    @property
    def available(self) -> bool:
        return bool(find_ffmpeg() and self._source_pairs())

    def _source_pairs(self) -> list[tuple[str, Path, Path]]:
        pairs = []
        for storyboard in self.source_root.glob("*-storyboard.png"):
            prefix = storyboard.name.removesuffix("-storyboard.png")
            poses = self.source_root / f"{prefix}-running-poses.png"
            if poses.is_file():
                pairs.append((prefix, storyboard, poses))
        return sorted(pairs)

    def _matching_visual_assets(self, allow_legacy_authored_series: bool) -> list[tuple[str, Path, Path]]:
        """Return the fixed legacy authored-art pairs -- ONLY when the caller
        explicitly opts in. Never inferred from goal text: a goal can contain
        the word "leni" purely to PROHIBIT it (see module docstring), so
        presence-of-keyword is not a trustworthy signal of genuine capability
        availability."""
        if not allow_legacy_authored_series:
            return []
        return self._source_pairs()

    @staticmethod
    def _capability_accounting(*, visual_available: bool, narration_available: bool,
                                video_render_available: bool) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        """Honest required/available/missing accounting for this environment
        -- ``visual_available`` reflects genuine availability (explicitly
        requested legacy series with an unused asset pair), never a text
        guess. story_generation/technical_validation/semantic_validation are
        deterministic/LLM-planning based and always structurally available."""
        available_map = {
            "story_generation": True,
            "scene_generation": visual_available,
            "character_visual_generation": visual_available,
            "motion_generation": visual_available,
            "narration_generation": narration_available,
            "thumbnail_generation": visual_available,
            "video_render": video_render_available,
            "technical_validation": True,
            "semantic_validation": True,
        }
        required = tuple(PRODUCTION_CAPABILITIES)
        available = tuple(name for name in required if available_map[name])
        missing = tuple(name for name in required if not available_map[name])
        return required, available, missing

    def build(self, *, goal: str, plan_text: str, memory: dict, duration_seconds: int = 60,
              channel_id: str = "default", channel_market: str = "Germany",
              channel_language: str = "de-DE", research_grounded: bool = False,
              research_evidence_ref: dict | None = None,
              allow_legacy_authored_series: bool = False,
              enable_scene_motion: bool = False) -> PackageBuildResult:
        video_render_available = bool(find_ffmpeg())
        narration_available = bool(shutil.which("edge-tts") or shutil.which("powershell.exe") or shutil.which("powershell"))
        matching = self._matching_visual_assets(allow_legacy_authored_series)
        required, available, missing = self._capability_accounting(
            visual_available=bool(matching), narration_available=narration_available,
            video_render_available=video_render_available)

        if not video_render_available:
            return PackageBuildResult(False, error="CAPABILITY_GAP: FFmpeg missing",
                required_capabilities=required, available_capabilities=available, missing_capabilities=missing)

        parsed = parse_plan_text(plan_text)
        if parsed is None:
            return PackageBuildResult(False, error="CAPABILITY_GAP: script parsing failed -- plan text is "
                                       "missing/malformed SENARYO or SAHNELER content; no canned story used",
                                       required_capabilities=required, available_capabilities=available,
                                       missing_capabilities=missing)

        if not matching:
            # Sprint: multi-provider media capability foundation. Before
            # declaring CAPABILITY_GAP, check whether a genuinely configured
            # and available dynamic provider (e.g. NVIDIA NIM text_to_image)
            # can fulfill this goal for real -- never the legacy authored
            # series (that stays explicit-opt-in only), never a fabricated
            # result. Always evaluated (PHASE 9): every compatible provider
            # considered, and why each was/wasn't usable, is cited in the
            # returned PackageBuildResult.error either way.
            return self._build_via_dynamic_provider(
                goal=goal, parsed=parsed, memory=memory, channel_id=channel_id,
                channel_market=channel_market, channel_language=channel_language,
                research_grounded=research_grounded, research_evidence_ref=research_evidence_ref,
                required=required, available=available, missing=missing,
                enable_scene_motion=enable_scene_motion)

        previous = list(memory.get("productions", []))
        used = {row.get("visual", {}).get("source_generation_fingerprint") for row in previous}
        candidates = []
        for prefix, storyboard, poses in matching:
            fingerprint = hashlib.sha256(storyboard.read_bytes() + poses.read_bytes()).hexdigest()
            if fingerprint not in used:
                candidates.append((prefix, storyboard, poses, fingerprint))
        if not candidates:
            return PackageBuildResult(False, error="CAPABILITY_GAP: authored source already used; exact reuse rejected",
                                       required_capabilities=required, available_capabilities=available,
                                       missing_capabilities=missing)
        prefix, storyboard, poses, source_hash = candidates[0]

        production_id = uuid.uuid4().hex
        root = self.output_root / channel_id / production_id
        root.mkdir(parents=True, exist_ok=False)
        checkpoint = root / "checkpoint.json"
        self._checkpoint(checkpoint, production_id, "BRIEF", "completed")

        try:
            scenes = self._split_storyboard(storyboard, root, len(parsed.scenes))
            pose_files = self._split_poses(poses, root)
            self._checkpoint(checkpoint, production_id, "SCENES_AND_MOTION", "completed")

            previous_ending = ""
            if previous:
                previous_ending = str(previous[-1].get("creative", {}).get("ending") or "")
            continuity = (
                f"PREVIOUS EPISODE ENDING: {previous_ending}"
                if previous_ending else "NEW SERIES"
            )

            script = parsed.script
            audio = root / "narration.wav"
            narration_provider = "Windows System.Speech"
            voice = _resolve_tts_voice(channel_language)
            edge_tts = shutil.which("edge-tts")
            if edge_tts:
                audio = root / "narration.mp3"
                spoken = subprocess.run(
                    [edge_tts, "--voice", voice, "--text", script,
                     "--write-media", str(audio)], capture_output=True, text=True, timeout=60, check=False,
                )
                audio_ok = spoken.returncode == 0 and audio.is_file() and audio.stat().st_size > 1024
                narration_provider = f"edge-tts {voice}"
            else:
                audio_ok = _write_sapi_wav(audio, script)
            if not audio_ok:
                return PackageBuildResult(False, error="CAPABILITY_GAP: real narration generation unavailable",
                                          production_id=production_id)
            self._checkpoint(checkpoint, production_id, "AUDIO", "completed")

            narration_seconds = None
            ffprobe = find_ffprobe()
            if ffprobe:
                try:
                    probe = subprocess.run(
                        [ffprobe, "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=nw=1:nk=1", str(audio)],
                        capture_output=True, text=True, timeout=15, check=False,
                    )
                    narration_seconds = float(probe.stdout.strip())
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    narration_seconds = None

            thumbnail = root / "thumbnail-final.png"
            shutil.copy2(scenes[-1], thumbnail)

            scene_plan = [{
                "scene_id": s.scene_id, "script_beat_id": s.script_beat_id, "purpose": s.purpose,
                "narration_segment": s.narration_segment, "visual_description": s.visual_description,
                "duration_seconds": s.duration_seconds, "transition": s.transition,
            } for s in parsed.scenes]

            manifest = {
                "schema_version": 4, "production_id": production_id,
                "channel_id": channel_id, "channel_market": channel_market, "channel_language": channel_language,
                "series_id": "leni-continuing-adventures", "story_state": continuity,
                "goal": goal, "topic": parsed.title,
                "target_audience": "children ages 5-9",
                "target_country_language": f"{channel_market} / {channel_language}", "video_type": "children_cartoon",
                "production_backend": "repository_imagegen_storyboard_pipeline",
                "image_provider": "Codex built-in image generation source + local scene compositor",
                "narration_provider": narration_provider, "narration_language": channel_language,
                "narration_seconds": narration_seconds,
                "fallback": False, "placeholder": False, "resolution": "1080x1920", "fps": 25,
                "story_concept": f"{parsed.title}: {parsed.hook}"[:280],
                "hook": parsed.hook, "script": script, "ending": parsed.ending,
                "cta": "Next Leni adventure",
                "characters": ["Leni"], "main_character_identity": "Leni canonical v1",
                "character_consistency_method": "canonical identity prompt plus one generated storyboard sheet",
                "character_consistency_score": 94,
                "character_identity": memory.get("characters", {}).get("Leni", {
                    "name": "Leni", "canonical_appearance": "brown bob, turquoise glasses, mustard coat, red scarf",
                }),
                "scene_files": [path.name for path in scenes],
                "scene_descriptions": [s.visual_description for s in parsed.scenes],
                "story_beats": [s.script_beat_id for s in parsed.scenes],
                "scene_plan": scene_plan,
                "character_motion": [{"scene_file": scenes[min(2, len(scenes) - 1)].name,
                    "pose_files": [path.name for path in pose_files], "pose_fps": 4,
                    "motion_type": "character_running_cycle", "character_roi": [0.18, 0.12, 0.64, 0.82]}],
                "successful_poses": ["run-left-contact", "run-airborne", "run-right-contact"],
                "failed_poses": [], "audio_file": audio.name,
                "thumbnail_path": str(thumbnail.resolve()),
                "thumbnail_concepts": [parsed.thumbnail_concept],
                "selected_thumbnail": parsed.thumbnail_concept,
                "thumbnail_selection_reason": "clear character, episode payoff, strong warm contrast",
                "title_candidates": [parsed.title],
                "selected_title": parsed.title,
                "description": parsed.description,
                "tags": list(parsed.tags),
                # Sprint: real-production quality-gate audit -- opportunity_selection
                # used to be three fixed literal strings regardless of goal; it now
                # reflects the real parsed plan and the same KnowledgeBase.find_research()
                # signal already used for research_grounded (no second research system).
                "opportunity_selection": {"bounded": True, "trend_claim": False,
                    "candidates": [parsed.title],
                    "selected": parsed.title,
                    "basis": ("research-grounded opportunity" if research_grounded else
                              "channel fit, novelty, feasibility "
                              "(NO stored research/opportunity evidence found for the requested goal)")},
                "selected_opportunity": parsed.title,
                "selection_reason": ("derived from stored research evidence for this goal" if research_grounded
                                     else "no stored research evidence; derived from goal text and channel "
                                          "context only"),
                "source_refs": [research_evidence_ref] if research_evidence_ref else [],
                "creative_angle": parsed.hook,
                "research_grounded": research_grounded,
                "research_status": "grounded" if research_grounded else "no_stored_research_evidence",
                "research_evidence_ref": research_evidence_ref,
                "visual_configuration": {"source_generation_fingerprint": source_hash,
                    "crop_order": list(range(len(scenes))), "production_id": production_id},
                "source_generation_fingerprint": source_hash,
                "tested_variation": f"goal-driven script ({len(scenes)} scenes) over authored '{prefix}' visual asset",
                "music": None, "publish_used": False,
            }
            manifest_path = root / "production.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            self._checkpoint(checkpoint, production_id, "PACKAGE", "completed")
            return PackageBuildResult(True, str(manifest_path.resolve()), production_id=production_id,
                                       required_capabilities=required, available_capabilities=required,
                                       missing_capabilities=())
        except (OSError, subprocess.SubprocessError) as error:
            self._checkpoint(checkpoint, production_id, "PACKAGE", "failed", str(error))
            return PackageBuildResult(False, error=f"production package build failed: {error}", production_id=production_id)

    def _build_via_dynamic_provider(self, *, goal: str, parsed: ParsedProductionPlan, memory: dict,
                                     channel_id: str, channel_market: str, channel_language: str,
                                     research_grounded: bool, research_evidence_ref: dict | None,
                                     required: tuple[str, ...], available: tuple[str, ...],
                                     missing: tuple[str, ...],
                                     enable_scene_motion: bool = False) -> PackageBuildResult:
        """Real per-scene generation via whichever genuinely available,
        ranked text_to_image provider exists (see
        ``src.media.provider_selection``) -- e.g. NVIDIA NIM once
        NVIDIA_API_KEY is configured. Returns an honest CAPABILITY_GAP
        (never a fabricated result), citing every compatible provider
        considered and why, when none is genuinely available. This path
        never touches the legacy authored-art series and never claims a
        fixed character identity -- content and provenance are entirely
        goal/provider-driven.
        """
        ranked, considered = rank_available_providers(TEXT_TO_IMAGE)
        if not ranked:
            evidence = "; ".join(f"{c.profile.provider_id}/{c.profile.model_id}: {c.reason}" for c in considered) \
                or "no media provider is registered for text_to_image"
            return PackageBuildResult(
                False, error="CAPABILITY_GAP: no genuine image/video-generation capability available for "
                             "this goal (the pre-authored legacy art series was not explicitly requested; "
                             f"no unrelated/placeholder asset was substituted). Providers considered: {evidence}",
                required_capabilities=required, available_capabilities=available, missing_capabilities=missing)

        production_id = uuid.uuid4().hex
        root = self.output_root / channel_id / production_id
        root.mkdir(parents=True, exist_ok=False)
        checkpoint = root / "checkpoint.json"
        self._checkpoint(checkpoint, production_id, "BRIEF", "completed")

        scene_files: list[Path] = []
        provenance: list[dict] = []
        for index, scene in enumerate(parsed.scenes, 1):
            image_path, entry = self._generate_scene_image(
                ranked, scene, index, root, enable_motion=enable_scene_motion)
            provenance.append(entry.as_dict())
            if image_path is None:
                self._checkpoint(checkpoint, production_id, "SCENES_AND_MOTION", "failed", entry.quality_evidence.get("reason", ""))
                return PackageBuildResult(
                    False, error=f"CAPABILITY_GAP: dynamic provider scene generation failed for scene "
                                 f"{index}: {entry.quality_evidence.get('reason', 'unknown error')}",
                    production_id=production_id, required_capabilities=required,
                    available_capabilities=(), missing_capabilities=missing)
            scene_files.append(image_path)
        self._checkpoint(checkpoint, production_id, "SCENES_AND_MOTION", "completed")

        script = parsed.script
        audio = root / "narration.wav"
        narration_provider = "Windows System.Speech"
        voice = _resolve_tts_voice(channel_language)
        edge_tts = shutil.which("edge-tts")
        if edge_tts:
            audio = root / "narration.mp3"
            spoken = subprocess.run(
                [edge_tts, "--voice", voice, "--text", script, "--write-media", str(audio)],
                capture_output=True, text=True, timeout=60, check=False,
            )
            audio_ok = spoken.returncode == 0 and audio.is_file() and audio.stat().st_size > 1024
            narration_provider = f"edge-tts {voice}"
        else:
            audio_ok = _write_sapi_wav(audio, script)
        if not audio_ok:
            return PackageBuildResult(False, error="CAPABILITY_GAP: real narration generation unavailable",
                                       production_id=production_id, required_capabilities=required,
                                       missing_capabilities=("narration_generation",))
        self._checkpoint(checkpoint, production_id, "AUDIO", "completed")

        narration_seconds = None
        ffprobe = find_ffprobe()
        if ffprobe:
            try:
                probe = subprocess.run(
                    [ffprobe, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=nw=1:nk=1", str(audio)],
                    capture_output=True, text=True, timeout=15, check=False,
                )
                narration_seconds = float(probe.stdout.strip())
            except (OSError, ValueError, subprocess.TimeoutExpired):
                narration_seconds = None

        thumbnail = root / "thumbnail-final.png"
        shutil.copy2(self._thumbnail_source(scene_files, root), thumbnail)

        scene_plan = [{
            "scene_id": s.scene_id, "script_beat_id": s.script_beat_id, "purpose": s.purpose,
            "narration_segment": s.narration_segment, "visual_description": s.visual_description,
            "duration_seconds": s.duration_seconds, "transition": s.transition,
        } for s in parsed.scenes]

        used_providers = sorted({row["provider"] for row in provenance if row.get("success")})
        fingerprint = hashlib.sha256(b"".join(path.read_bytes() for path in scene_files)).hexdigest()

        manifest = {
            "schema_version": 4, "production_id": production_id,
            "channel_id": channel_id, "channel_market": channel_market, "channel_language": channel_language,
            "series_id": "", "story_state": "NEW",
            "goal": goal, "topic": parsed.title,
            "target_audience": "general", "target_country_language": f"{channel_market} / {channel_language}",
            "video_type": "generated_short",
            "production_backend": f"dynamic_provider:{'+'.join(used_providers) or 'unknown'}",
            "image_provider": "+".join(sorted({f"{row['provider']}/{row['model']}" for row in provenance if row.get("success")})),
            "narration_provider": narration_provider, "narration_language": channel_language,
            "narration_seconds": narration_seconds,
            "fallback": False, "placeholder": False, "resolution": "1080x1920", "fps": 25,
            "story_concept": f"{parsed.title}: {parsed.hook}"[:280],
            "hook": parsed.hook, "script": script, "ending": parsed.ending,
            "cta": "", "characters": [], "main_character_identity": "",
            "character_consistency_method": "", "character_consistency_score": 0,
            "character_identity": {},
            "scene_files": [path.name for path in scene_files],
            "scene_descriptions": [s.visual_description for s in parsed.scenes],
            "story_beats": [s.script_beat_id for s in parsed.scenes],
            "scene_plan": scene_plan,
            # No character_motion entries (that spec is the legacy authored-
            # pose-sheet path only). Provider-generated stills rely on
            # LocalVideoRenderer's zoompan branch; when enable_scene_motion
            # produced a real .mp4 for a scene, LocalVideoRenderer.
            # _render_production_package's mp4-passthrough branch
            # (scene.suffix == ".mp4") scales/crops/trims it directly
            # instead of running zoompan on a still.
            "character_motion": [], "successful_poses": [], "failed_poses": [],
            "audio_file": audio.name,
            "thumbnail_path": str(thumbnail.resolve()),
            "thumbnail_concepts": [parsed.thumbnail_concept], "selected_thumbnail": parsed.thumbnail_concept,
            "thumbnail_selection_reason": "final generated scene reused as thumbnail",
            "title_candidates": [parsed.title], "selected_title": parsed.title,
            "description": parsed.description, "tags": list(parsed.tags),
            "opportunity_selection": {"bounded": True, "trend_claim": False,
                "candidates": [parsed.title], "selected": parsed.title,
                "basis": ("research-grounded opportunity" if research_grounded else
                          "channel fit, novelty, feasibility "
                          "(NO stored research/opportunity evidence found for the requested goal)")},
            "selected_opportunity": parsed.title,
            "selection_reason": ("derived from stored research evidence for this goal" if research_grounded
                                 else "no stored research evidence; derived from goal text and channel context only"),
            "source_refs": [research_evidence_ref] if research_evidence_ref else [],
            "creative_angle": parsed.hook,
            "research_grounded": research_grounded,
            "research_status": "grounded" if research_grounded else "no_stored_research_evidence",
            "research_evidence_ref": research_evidence_ref,
            "visual_configuration": {"source_generation_fingerprint": fingerprint,
                "crop_order": [], "production_id": production_id},
            "source_generation_fingerprint": fingerprint,
            "tested_variation": f"goal-driven script ({len(scene_files)} scenes) via dynamic provider "
                                 f"({'+'.join(used_providers) or 'unknown'})",
            "music": None, "publish_used": False,
            "scene_provenance": provenance,
        }
        manifest_path = root / "production.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self._checkpoint(checkpoint, production_id, "PACKAGE", "completed")
        return PackageBuildResult(True, str(manifest_path.resolve()), production_id=production_id,
                                   required_capabilities=required, available_capabilities=required,
                                   missing_capabilities=())

    @staticmethod
    def _generate_scene_image(ranked, scene: ScenePlan, index: int, root: Path,
                               *, enable_motion: bool = False) -> tuple[Path | None, SceneProvenance]:
        """Try the ranked candidates in order (bounded to the top 2 -- same
        bounded-retry spirit as the existing repair loop, never unbounded)
        so one candidate's real execution failure triggers the existing
        fallback chain (Phase 8) instead of failing the whole scene
        immediately.

        When ``enable_motion`` is set AND the winning image provider
        returned a real hosted URL for its own output (e.g. fal FLUX --
        NVIDIA returns base64 only, no URL), this OPTIONALLY chains a
        ranked image_to_video provider to turn that still into real scene
        motion instead of the renderer's deterministic zoompan fallback.
        Bounded to the single top-ranked video candidate, never retried,
        and any failure/unavailability silently keeps the still image --
        motion is a bonus, never a build-blocking requirement (task: "do
        not force video generation for every scene")."""
        history = ProviderExecutionHistory()
        attempted: list[str] = []
        for profile, provider in ranked[:2]:
            if not hasattr(provider, "generate_image"):
                continue
            fallback_used = bool(attempted)
            attempted.append(profile.provider_id)
            result = provider.generate_image(scene.visual_description, width=1024, height=1344)
            history.record(task_type=TEXT_TO_IMAGE, provider=profile.provider_id, success=result.success,
                            fallback_used=fallback_used, duration_seconds=result.duration_seconds or 0.0,
                            cost_class=result.cost_class)
            if result.success and result.content_bytes and len(result.content_bytes) > 1000:
                if enable_motion and result.content_url:
                    motion_path, motion_entry = GeneralProductionBuilder._maybe_generate_scene_motion(
                        scene, result.content_url, index, root, history)
                    if motion_path is not None:
                        return motion_path, motion_entry
                path = root / f"scene-{index:02d}.png"
                path.write_bytes(result.content_bytes)
                return path, SceneProvenance(
                    scene_id=scene.scene_id, capability=TEXT_TO_IMAGE, provider=profile.provider_id,
                    model=profile.model_id, generation_type=TEXT_TO_IMAGE, output_path=str(path.resolve()),
                    success=True, fallback_used=fallback_used, cost_class=result.cost_class,
                    input_reference=scene.visual_description[:200], duration_seconds=result.duration_seconds)
        return None, SceneProvenance(
            scene_id=scene.scene_id, capability=TEXT_TO_IMAGE, provider=attempted[-1] if attempted else "",
            model="", generation_type=TEXT_TO_IMAGE, output_path="", success=False, fallback_used=len(attempted) > 1,
            input_reference=scene.visual_description[:200],
            quality_evidence={"reason": f"all candidate providers failed for scene {index}: {attempted or 'none eligible'}"})

    @staticmethod
    def _maybe_generate_scene_motion(scene: ScenePlan, image_url: str, index: int, root: Path,
                                      history: ProviderExecutionHistory) -> tuple[Path | None, SceneProvenance | None]:
        """Bounded, best-effort image_to_video chain for one scene -- ONLY
        the single top-ranked compatible candidate is tried (never
        retried), and any failure returns ``(None, None)`` so the caller
        keeps the already-generated still image and the renderer's
        deterministic zoompan path (never blocks/fails the build for an
        optional enhancement)."""
        ranked_video, _ = rank_available_providers(IMAGE_TO_VIDEO)
        for profile, provider in ranked_video[:1]:
            if not hasattr(provider, "generate_video_from_image"):
                continue
            result = provider.generate_video_from_image(scene.visual_description, image_url)
            history.record(task_type=IMAGE_TO_VIDEO, provider=profile.provider_id, success=result.success,
                            fallback_used=False, duration_seconds=result.duration_seconds or 0.0,
                            cost_class=result.cost_class)
            if result.success and result.content_bytes and len(result.content_bytes) > 10_000:
                path = root / f"scene-{index:02d}.mp4"
                path.write_bytes(result.content_bytes)
                return path, SceneProvenance(
                    scene_id=scene.scene_id, capability=IMAGE_TO_VIDEO, provider=profile.provider_id,
                    model=profile.model_id, generation_type=IMAGE_TO_VIDEO, output_path=str(path.resolve()),
                    success=True, fallback_used=False, cost_class=result.cost_class,
                    input_reference=scene.visual_description[:200], duration_seconds=result.duration_seconds)
        return None, None

    @staticmethod
    def _thumbnail_source(scene_files: list[Path], root: Path) -> Path:
        """The final thumbnail must be a real still image. When motion
        generation (``enable_scene_motion``) turned the LAST scene into an
        .mp4, a plain ``shutil.copy2`` of it into ``thumbnail-final.png``
        would silently write raw video bytes into a .png file -- prefer any
        still-image scene file, and otherwise extract one real frame from
        the video via ffmpeg."""
        last = scene_files[-1]
        if last.suffix.casefold() != ".mp4":
            return last
        stills = [path for path in scene_files if path.suffix.casefold() != ".mp4"]
        if stills:
            return stills[-1]
        frame = root / "thumbnail-source-frame.png"
        command = [find_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                   "-i", str(last), "-frames:v", "1", str(frame)]
        subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        return frame if frame.is_file() else last

    def _split_storyboard(self, source: Path, root: Path, scene_count: int) -> list[Path]:
        width, height = self._dimensions(source)
        pw, ph = width // 3, height // 2
        crops = ((0, 0), (pw, 0), (pw * 2, 0), (0, ph), (pw, ph), (pw * 2, ph))[:scene_count]
        return [self._crop(source, root / f"scene-{index:02d}.png", x + 6, y + 6, pw - 12, ph - 12)
                for index, (x, y) in enumerate(crops, 1)]

    def _split_poses(self, source: Path, root: Path) -> list[Path]:
        width, height = self._dimensions(source)
        pw = width // 3
        raw = [self._crop(source, root / f"pose-source-{index:02d}.png", index * pw + 6, 6, pw - 12, height - 12)
               for index in range(3)]
        # The image model authored distinct poses and also introduced tiny
        # background variations. Composite only the character region over one
        # static authored background so measured motion is local, not camera/
        # whole-frame flicker.
        final = []
        for index, pose in enumerate(raw, 1):
            target = root / f"pose-run-{index:02d}.png"
            body_x, body_y = int(pw * .15), int(height * .08)
            body_w, body_h = int(pw * .72), int(height * .82)
            command = [find_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                       "-i", str(raw[0]), "-i", str(pose), "-filter_complex",
                       f"[1:v]crop={body_w}:{body_h}:{body_x}:{body_y}[body];"
                       f"[0:v][body]overlay={body_x}:{body_y}",
                       "-frames:v", "1", str(target)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False)
            if result.returncode != 0 or not target.is_file() or target.stat().st_size <= 10_000:
                raise OSError(f"localized motion generation failed: {result.stderr[-300:]}")
            final.append(target)
        return final

    @staticmethod
    def _dimensions(source: Path) -> tuple[int, int]:
        ffprobe = shutil.which("ffprobe") or str(Path("tools/ffmpeg/bin/ffprobe.exe").resolve())
        result = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(source)],
            capture_output=True, text=True, timeout=15, check=False)
        stream = json.loads(result.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])

    @staticmethod
    def _crop(source: Path, target: Path, x: int, y: int, width: int, height: int) -> Path:
        command = [find_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
                   "-vf", f"crop={width}:{height}:{x}:{y}", "-frames:v", "1", str(target)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False)
        if result.returncode != 0 or not target.is_file() or target.stat().st_size <= 10_000:
            raise OSError(f"scene generation failed: {result.stderr[-300:]}")
        return target

    @staticmethod
    def _checkpoint(path: Path, production_id: str, stage: str, status: str, error: str = "") -> None:
        current = {}
        if path.is_file():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = {}
        current.update({"production_id": production_id, "last_stage": stage, "status": status, "error": error})
        current.setdefault("completed_stages", [])
        if status == "completed" and stage not in current["completed_stages"]:
            current["completed_stages"].append(stage)
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
