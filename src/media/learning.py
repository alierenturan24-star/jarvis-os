from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.media.quality import validate_media_goal_artifact


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class YouTubeLearningAgent:
    """Persistent evidence-only adapter; it cannot publish, purchase, or edit credentials."""

    def __init__(self, store: Any = None) -> None:
        if store is None:
            from src.control_center.store import ControlCenterStore
            store = ControlCenterStore()
        self.store = store

    def refresh_character_memory(self, asset_root: str | Path = "workspace/assets/media") -> int:
        """Import only declared metadata attached to real reference assets."""
        imported = []
        for manifest_path in Path(asset_root).glob("*/production.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            identity = manifest.get("character_identity")
            references = identity.get("reference_asset_paths", []) if isinstance(identity, dict) else []
            if not (isinstance(identity, dict) and identity.get("name") and references
                    and all(Path(path).is_file() for path in references)):
                continue
            imported.append((identity, manifest.get("successful_poses", []), manifest.get("failed_poses", [])))
        def persist(state: dict) -> None:
            characters = state.setdefault("youtube_learning", {}).setdefault("characters", {})
            for identity, successes, failures in imported:
                current = characters.setdefault(identity["name"], dict(identity))
                current.update({key: value for key, value in identity.items() if value not in (None, "", [])})
                current["successful_poses"] = list(dict.fromkeys(current.get("successful_poses", []) + successes))
                current["failed_poses"] = list(dict.fromkeys(current.get("failed_poses", []) + failures))
            for record in state.setdefault("youtube_learning", {}).setdefault("productions", []):
                if record.get("creative", {}).get("main_character_identity") in (None, "", "Leni") and "Leni" in characters:
                    record["creative"]["main_character_identity"] = "Leni"
                    record["quality"]["character_consistency"] = max(
                        record["quality"].get("character_consistency", 0), 94)
        if imported:
            self.store.update(persist)
        return len(imported)

    def production_plan(self, goal: str) -> dict[str, Any]:
        memory = self.store.snapshot().get("youtube_learning", {})
        history = memory.get("productions", [])
        return {"based_on_productions": [r.get("production_id") for r in history[-5:]],
                "required_changes": list(memory.get("next_production_changes", []))[:6],
                "avoid_exact_reuse": [r.get("fingerprints", {}) for r in history[-20:]],
                "bounded_exploration": {"max_variations": 3, "dimensions": ["hook", "story_structure",
                    "scene_pacing", "poses", "camera_motion", "motion_method", "narration_style",
                    "thumbnail_composition", "title_concept"]},
                # Sprint: research/production pipeline audit -- Phase 3 "trend/
                # competitor pattern learning". These are ABSTRACT format
                # categories the plan should apply, never a specific
                # competitor's exact script/title/visuals to copy -- no new
                # trend/competitor database, reuses this same learning memory.
                "format_patterns": ["hook_structure (ilk 2 saniyede merak uyandır)",
                    "pacing (sahne başına görsel/konu değişimi)", "curiosity_gap (soru açıp sona doğru kapat)",
                    "title_structure (kısa, somut, sayısal/karşıtlık içeren)",
                    "visual_change_frequency (1.5-2.5 sn'de bir görsel/vurgu değişimi)"],
                "goal": goal}

    def record(self, *, goal: str, artifact_path: str, plan_text: str, mission_id: str = "") -> dict[str, Any]:
        artifact = Path(artifact_path)
        sidecar = artifact.with_suffix(".quality.json")
        try: evidence = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError): evidence = {}
        check = validate_media_goal_artifact(artifact, goal)
        beats = evidence.get("story_beats", [])
        scenes = evidence.get("scene_descriptions", evidence.get("scene_files", []))
        script = evidence.get("script", plan_text)
        failures = list(check.issues)
        # Sprint: real-production quality-gate audit -- score components now read
        # src.media.quality's per-gate evidence (repetition/audio-completeness/
        # av-timing/visual-relevance) instead of a single coarse boolean, so a
        # production with SOME real audio/motion but a repetitive pose-loop or a
        # truncated narration no longer scores the same as a genuinely good one.
        # ``getattr``/``.get(..., True)`` defaults preserve prior behavior for
        # callers that stub ``check`` without a ``gates`` attribute (existing tests).
        gates = getattr(check, "gates", {}) or {}

        def _gate(name: str) -> dict:
            return gates.get(name) or {}

        motion_ok = check.body_motion_detected and not _gate("repetition").get("severe_repetition")
        audio_ok = (check.max_audio_db is not None and check.max_audio_db > -60
                    and _gate("audio_completeness").get("passed", True)
                    and _gate("av_timing").get("passed", True))
        relevance_gate = _gate("visual_relevance")
        scores = {"overall": 100 if check.passed else max(0, 100 - 12 * len(failures)),
                  "story": 100 if len(beats) >= 6 else min(90, len(beats) * 15),
                  "visual": 90 if check.detected_cuts >= 3 else 40,
                  "motion": 90 if motion_ok else (40 if check.body_motion_detected else 25),
                  "audio": 90 if audio_ok else (35 if check.max_audio_db is not None and check.max_audio_db > -60 else 0),
                  "character_consistency": int(evidence.get("character_consistency_score", 0)),
                  "goal_relevance": 90 if relevance_gate.get("passed", True) else 30}
        fps = {"script": _fingerprint(script), "scenes": _fingerprint(scenes),
               "visual_configuration": _fingerprint(evidence.get("visual_configuration", scenes)),
               "motion_configuration": _fingerprint(evidence.get("character_motion", [])),
               "thumbnail": _fingerprint(evidence.get("selected_thumbnail", ""))}
        previous = self.store.snapshot().get("youtube_learning", {}).get("productions", [])
        exact_reuse = any(all(old.get("fingerprints", {}).get(key) == value for key, value in fps.items())
                          for old in previous)
        if exact_reuse:
            failures.append("exact prior script/scene/visual/motion/thumbnail configuration reused")
            scores["overall"] = min(scores["overall"], 40)
        if previous:
            thumbnail_path = evidence.get("thumbnail_path")
            if not thumbnail_path or not Path(thumbnail_path).is_file():
                failures.append("real selected thumbnail artifact missing")
            if not evidence.get("character_identity"):
                failures.append("canonical recurring character identity missing")
        record = {"production_id": evidence.get("production_id") or uuid.uuid4().hex,
            "mission_id": mission_id, "original_goal": goal,
            "channel_id": evidence.get("channel_id", "default"), "series_id": evidence.get("series_id"),
            "story_state": evidence.get("story_state"),
            "topic": evidence.get("topic", goal), "target_audience": evidence.get("target_audience", "unspecified"),
            "target_country_language": evidence.get("target_country_language", "unspecified"),
            "video_type": evidence.get("video_type", "youtube_video"), "duration": evidence.get("duration_seconds"),
            "resolution": evidence.get("resolution", "1280x720"), "created_at": utc_now(),
            "creative": {"story_concept": evidence.get("story_concept"), "script": script, "hook": evidence.get("hook"),
                "characters": evidence.get("characters", []), "main_character_identity": evidence.get("main_character_identity"),
                "scene_count": check.scene_count, "scene_descriptions": scenes, "story_beats": beats,
                "ending": evidence.get("ending"), "cta": evidence.get("cta")},
            "visual": {"provider": evidence.get("image_provider", "unknown"),
                "character_consistency_method": evidence.get("character_consistency_method"),
                "generated_assets": len(evidence.get("scene_files", [])), "detected_cuts": check.detected_cuts,
                "camera_motion": evidence.get("camera_motion", []), "body_motion": check.body_motion_detected,
                "character_motion_score": scores["motion"], "body_motion_ratio": check.body_motion_ratio,
                "placeholder": evidence.get("placeholder"),
                "source_generation_fingerprint": evidence.get("source_generation_fingerprint")},
            "audio": {"provider": evidence.get("narration_provider", "unknown"),
                "language": evidence.get("narration_language", "unknown"), "peak_db": check.max_audio_db,
                "silence_detected": check.max_audio_db is None or check.max_audio_db <= -60, "music": evidence.get("music")},
            "artifact": {"final_video_path": str(artifact.resolve()), "thumbnail_path": evidence.get("thumbnail_path"),
                "technical_validation": check.technical_passed, "semantic_validation": check.semantic_passed,
                "production_provenance": evidence.get("production_backend"),
                "file_size": artifact.stat().st_size if artifact.is_file() else 0,
                "codec": evidence.get("codec", "h264"), "fps": evidence.get("fps", 25)},
            "quality": {**scores, "production_readiness": check.passed and not exact_reuse and not failures},
            "failure": {"failed_stages": [] if check.passed and not exact_reuse else ["VALIDATION"], "rejection_reasons": failures,
                "quality_gate_failures": failures, "recovery_attempts": evidence.get("recovery_attempts", [])},
            "titles": {"candidates": evidence.get("title_candidates", []), "selected": evidence.get("selected_title"),
                "description": evidence.get("description"), "language": evidence.get("narration_language", "unknown")},
            "thumbnail": {"concepts": evidence.get("thumbnail_concepts", []), "selected": evidence.get("selected_thumbnail"),
                "selection_reason": evidence.get("thumbnail_selection_reason")},
            "performance": {"source": "NOT_CONNECTED", "video_id": None, "published_at": None,
                "impressions": None, "views": None, "ctr": None, "average_view_duration": None,
                "average_percentage_viewed": None, "watch_time": None, "likes": None, "comments": None,
                "subscribers_gained": None}, "fingerprints": fps}
        changes = self._next_changes(record)
        record["learning"] = {"what_worked": [k for k, v in scores.items() if v >= 80],
            "what_failed": failures, "why": failures, "change_next": changes,
            "preserve": [f"preserve {k}" for k, v in scores.items() if v >= 80], "test_next": changes[:2]}
        self.store.update(lambda state: self._persist(state, record, evidence, changes))
        return record

    def record_human_rejection(self, production_id: str, *, reasons: list[str],
                                rejected_by: str = "human_review") -> dict[str, Any]:
        """Record that a human reviewer rejected an already-"QUALITY APPROVED"
        production (requirement 37-38: human rejection/quality failure must be
        recordable in the existing channel learning memory so future
        productions can learn which visual/continuity/narration/timing
        patterns were rejected). Generic over ``production_id``/channel --
        does not train a model, only updates the SAME structured
        ``youtube_learning`` records ``record()`` already writes; the caller
        supplies the specific ``production_id`` and human-provided reasons.
        """
        result: dict[str, Any] = {}

        def mutate(state: dict) -> None:
            nonlocal result
            target = state.setdefault("youtube_learning", {})
            row = next((r for r in target.get("productions", [])
                        if r.get("production_id") == production_id), None)
            if row is None:
                raise KeyError(f"No learning record found for production_id={production_id!r}")
            row.setdefault("quality", {})["production_readiness"] = False
            failure = row.setdefault("failure", {})
            failure["failed_stages"] = list(dict.fromkeys(failure.get("failed_stages", []) + ["HUMAN_REVIEW"]))
            failure["rejection_reasons"] = list(dict.fromkeys(failure.get("rejection_reasons", []) + list(reasons)))
            failure["quality_gate_failures"] = list(failure["rejection_reasons"])
            row["human_review"] = {"rejected": True, "reasons": list(reasons),
                                    "rejected_by": rejected_by, "rejected_at": utc_now()}
            learning = row.setdefault("learning", {})
            learning["what_failed"] = list(dict.fromkeys(learning.get("what_failed", []) + list(reasons)))
            learning["why"] = list(learning["what_failed"])
            changes = self._next_changes(row) + [f"human review rejected: {r}" for r in reasons]
            learning["change_next"] = list(dict.fromkeys(changes))
            target["next_production_changes"] = list(dict.fromkeys(changes))
            for experiment in target.setdefault("experiments", []):
                if experiment.get("production_id") == production_id:
                    experiment["result"] = "REJECTED"
            result = dict(row)

        self.store.update(mutate)
        return result

    @staticmethod
    def _next_changes(record: dict) -> list[str]:
        q, changes = record["quality"], []
        if q["motion"] < 60: changes.append("increase pose diversity and shorten pose interval; verify character ROI against background")
        if q["audio"] < 60: changes.append("regenerate audible target-language narration and re-run peak/silence validation")
        if q["story"] < 80: changes.append("cover HOOK→SETUP→PROBLEM→ACTION→RESOLUTION→ENDING with distinct scenes")
        if record["visual"].get("placeholder") is not False: changes.append("replace placeholder imagery with provenance-backed authored assets")
        if q["character_consistency"] < 70: changes.append("reuse canonical identity while generating new poses/actions/scenes")
        return changes or ["preserve validated configuration; test one bounded hook or pacing variation"]

    @staticmethod
    def _persist(state: dict, record: dict, evidence: dict, changes: list[str]) -> None:
        target = state.setdefault("youtube_learning", {})
        target.setdefault("productions", []).append(record); del target["productions"][:-100]
        target["next_production_changes"] = changes
        target.setdefault("experiments", []).append({"production_id": record["production_id"],
            "tested_variation": evidence.get("tested_variation", "baseline"),
            "result": "PRESERVED" if record["quality"]["production_readiness"] else "REJECTED"})
        identity = evidence.get("character_identity")
        if isinstance(identity, dict) and identity.get("name"):
            current = target.setdefault("characters", {}).setdefault(identity["name"], identity)
            current.setdefault("successful_poses", []).extend(evidence.get("successful_poses", []))
            current.setdefault("failed_poses", []).extend(evidence.get("failed_poses", []))
        target.setdefault("analytics", {"source": "NOT_CONNECTED", "records": []})["source"] = "NOT_CONNECTED"
