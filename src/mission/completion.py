from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from src.jobs.task_status import TaskStatus


class ArtifactType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    DOCUMENT = "document"


ARTIFACT_EXTENSIONS: dict[ArtifactType, frozenset[str]] = {
    ArtifactType.VIDEO: frozenset({".mp4", ".webm", ".mov", ".mkv"}),
    ArtifactType.AUDIO: frozenset({".mp3", ".wav", ".m4a", ".ogg"}),
    ArtifactType.IMAGE: frozenset({".png", ".jpg", ".jpeg", ".webp"}),
    ArtifactType.DOCUMENT: frozenset({".md", ".txt", ".pdf", ".doc", ".docx", ".csv", ".json", ".html"}),
}

_ARTIFACT_LABELS = {
    ArtifactType.VIDEO: "gerçek video üretimi",
    ArtifactType.AUDIO: "gerçek ses üretimi",
    ArtifactType.IMAGE: "gerçek görsel üretimi",
    ArtifactType.DOCUMENT: "gerçek rapor/dosya üretimi",
}

_PATH_METADATA_KEYS = {
    "artifact_path", "artifact_paths", "artifacts", "output_path", "output_paths",
    "file_path", "file_paths", "report_path", "saved_path",
}


@dataclass(frozen=True)
class CompletionRequirement:
    kind: str
    name: str
    remaining: str
    domain: str = "general"


@dataclass(frozen=True)
class RequirementStatus:
    requirement: CompletionRequirement
    satisfied: bool
    paths: tuple[str, ...] = ()
    # Round 4 repair (real live-mission evidence): a rendered artifact that
    # merely hasn't PASSED quality validation yet (still in-progress,
    # timed-out mid quality_check, or genuinely failed a gate) must not be
    # reported the SAME way as "no artifact was ever produced" -- both used
    # to collapse into ``satisfied=False`` with no distinguishing signal.
    # True only for an unsatisfied ARTIFACT requirement where a real,
    # non-empty, correctly-extensioned file was found on disk (see
    # ``_artifact_file_exists`` below) among the reported candidate paths --
    # never for other requirement kinds. Does NOT relax ``satisfied``
    # itself: a mission stays incomplete until the artifact actually PASSES
    # quality validation.
    rendered_not_approved: bool = False


@dataclass(frozen=True)
class GoalCompletion:
    requirements: tuple[RequirementStatus, ...]

    @property
    def satisfied(self) -> bool:
        return all(item.satisfied for item in self.requirements)

    @property
    def missing(self) -> tuple[RequirementStatus, ...]:
        return tuple(item for item in self.requirements if not item.satisfied)


def has_youtube_production_intent(text: str) -> bool:
    """Recognise real production even when noun and verb are not adjacent."""
    lowered = (text or "").casefold()
    return (
        any(cue in lowered for cue in ("youtube", "video", "short", "çizgi film"))
        and any(cue in lowered for cue in ("üret", "oluştur", "hazırla", "render", "kaydet"))
    )


def infer_completion_requirements(text: str, departments: Iterable[str] = ()) -> tuple[CompletionRequirement, ...]:
    """Infer only concrete outputs explicitly requested by the user.

    Research/planning wording deliberately does not imply a media artifact.
    Evidence requirements are added only for an explicit repository evaluation
    goal and only for evidence departments that are part of the selected plan.
    """

    lowered = (text or "").casefold()
    requirements: list[CompletionRequirement] = []

    production = r"(?:üret|oluştur|hazırla|render|kaydet)"
    if re.search(rf"(?:video|youtube\s+videosu|shorts?|Ã§izgi\s+film)\w*\s+{production}", lowered) or re.search(
        rf"{production}\w*[^.!?]{{0,30}}(?:video|shorts?|Ã§izgi\s+film)", lowered
    ):
        requirements.append(_artifact_requirement(ArtifactType.VIDEO))

    # Keep the correctly encoded Turkish form explicit for live UTF-8 input;
    # older source fixtures also exercise the legacy mojibake spellings above.
    if "çizgi film" in lowered and any(cue in lowered for cue in ("üret", "oluştur", "hazırla", "render", "kaydet")):
        video_requirement = _artifact_requirement(ArtifactType.VIDEO)
        if video_requirement not in requirements:
            requirements.append(video_requirement)

    # Generic "Video üret" keeps the established artifact-only contract.
    # The richer evidence contract is for an explicit YouTube production.
    youtube_production = has_youtube_production_intent(text) and any(
        cue in lowered for cue in ("youtube", "short", "çizgi film")
    )
    if youtube_production:
        if not any(item.kind == "artifact" and item.name == ArtifactType.VIDEO.value for item in requirements):
            requirements.append(CompletionRequirement(
                "artifact", ArtifactType.VIDEO.value, "gerçek YouTube video artifact eksik", "youtube"
            ))
        requirements.extend(CompletionRequirement("youtube_evidence", name, remaining, "youtube") for name, remaining in (
            ("youtube_opportunity_or_content_plan", "YouTube fırsat/içerik planı eksik"),
            ("technical_validation", "YouTube teknik doğrulaması eksik"),
            ("semantic_validation", "YouTube semantik doğrulaması eksik"),
            ("production_provenance", "YouTube production provenance eksik"),
            ("story_coverage", "YouTube story coverage eksik"),
            ("motion_evidence", "YouTube motion kanıtı eksik"),
            ("audio_evidence", "YouTube audio kanıtı eksik"),
            ("thumbnail_artifact_or_reasoned_not_required", "YouTube thumbnail kanıtı eksik"),
            ("youtube_learning_persisted", "YouTube learning persistence eksik"),
            ("publish_not_used", "publish-not-used güvenlik kanıtı eksik"),
        ))

    if re.search(rf"(?:ses|voiceover|seslendirme)\w*\s+{production}", lowered) or re.search(
        rf"{production}\w*[^.!?]{{0,30}}(?:ses|voiceover|seslendirme)", lowered
    ):
        requirements.append(_artifact_requirement(ArtifactType.AUDIO))

    if re.search(rf"(?:thumbnail|görsel|resim)\w*\s+{production}", lowered) or re.search(
        rf"{production}\w*[^.!?]{{0,30}}(?:thumbnail|görsel|resim)", lowered
    ):
        requirements.append(_artifact_requirement(ArtifactType.IMAGE))

    if re.search(rf"(?:rapor|dosya)\w*\s+{production}", lowered) or re.search(
        rf"{production}\w*[^.!?]{{0,30}}(?:rapor|dosya)", lowered
    ):
        requirements.append(_artifact_requirement(ArtifactType.DOCUMENT))

    department_set = set(departments)
    # Requirements describe the user's goal, not the plan selected for it.
    # Otherwise a routing bug which omits finance also erases the evidence
    # invariant and turns a research-only task into false completion.
    finance_strategy_goal = any(cue in lowered for cue in (
        "finance engine", "stratej", "strategy lab", "backtest", "paper",
        "out-of-sample", "oos", "overfitting", "qualified",
    )) and any(cue in lowered for cue in (
        "backtest", "paper", "out-of-sample", "oos", "qualified", "stratej", "strategy lab",
    ))
    if finance_strategy_goal:
        semantic = []
        if any(cue in lowered for cue in ("novel", "exploration", "bounded", "keşfet", "kesfet")):
            semantic.append(("novel_strategy_candidates", "novel strategy candidate provenance missing"))
        if any(cue in lowered for cue in ("new strateg", "yeni stratej", "yeni gÃ¼venli", "keÅŸfet")):
            semantic.append(("novel_strategy_candidates", "novel strategy candidate provenance missing"))
        if any(cue in lowered for cue in ("multi-asset", "multi asset", "farklÄ± asset", "farklÄ± varlÄ±k")) or (
            "asset" in lowered and "fark" in lowered
        ):
            semantic.append(("multi_asset_evidence", "multiple asset evidence missing"))
        if any(cue in lowered for cue in ("regime", "rejim", "piyasa koÅŸul")):
            semantic.append(("regime_evidence", "market regime evidence missing"))
        if any(cue in lowered for cue in ("timeframe", "time frame", "zaman dilim")):
            semantic.append(("multi_timeframe_evidence", "multiple timeframe evidence missing"))
        semantic.extend((
            ("strategy_research", "alternatif strateji araştırması eksik"),
            ("strategy_comparison", "strategy comparison missing"),
            ("backtest", "karşılaştırmalı backtest kanıtı eksik"),
            ("oos", "insufficient OOS evidence"),
            ("risk_performance", "risk/performance karşılaştırması eksik"),
            ("qualification", "strategy qualification evidence missing"),
            ("paper_decision", "paper promotion not reached"),
        ))
        if "learning" in department_set or any(cue in lowered for cue in ("learning", "öğren", "ogren", "hafıza", "memory")):
            semantic.append(("learning_persisted", "finance learning/history was not persisted"))
        if any(cue in lowered for cue in ("public market data", "gerçek market data", "gerçek piyasa veri")):
            semantic.append(("market_data", "real public market data evidence missing"))
        if any(cue in lowered for cue in ("gerçek para", "real money", "live money")):
            semantic.append(("real_money_not_used", "real-money-not-used safety evidence missing"))
        requirements.extend(CompletionRequirement("finance_evidence", name, remaining, "finance")
                            for name, remaining in dict.fromkeys(semantic))
    repo_signal = any(word in lowered for word in ("repo", "repository", "github", "açık kaynak proje"))
    if repo_signal:
        if "github" in department_set and any(word in lowered for word in ("repo bul", "github", "repo araştır", "reposunu araştır")):
            requirements.append(CompletionRequirement("evidence", "github", "GitHub repo kanıtının tamamlanması"))
        if "github" in department_set and any(word in lowered for word in (
            "readme", "dokümantasyon", "documentation", "lisans", "claude code", "codex", "mcp",
        )):
            requirements.append(CompletionRequirement("evidence", "readme", "README/dokümantasyon kanıtının tamamlanması"))
        explicit_evidence = {
            "evaluation": ("değerlendir", "evaluation", "güvenli", "uygun mu", "risk"),
            "sandbox": ("sandbox",),
            "integration": ("integration", "entegrasyon"),
        }
        for department, cues in explicit_evidence.items():
            if department in department_set and any(cue in lowered for cue in cues):
                requirements.append(CompletionRequirement(
                    kind="evidence", name=department,
                    remaining=f"{department} kanıtının tamamlanması",
                ))

    return tuple(dict.fromkeys(requirements))


def _artifact_requirement(kind: ArtifactType) -> CompletionRequirement:
    return CompletionRequirement(kind="artifact", name=kind.value, remaining=_ARTIFACT_LABELS[kind])


def evaluate_goal_completion(mission) -> GoalCompletion:
    requirements = tuple(getattr(mission, "completion_requirements", ()) or ())
    if not requirements:
        requirements = infer_completion_requirements(mission.title, mission.departments)

    paths = tuple(_reported_paths(mission))
    statuses: list[RequirementStatus] = []
    for requirement in requirements:
        if requirement.kind == "artifact":
            kind = ArtifactType(requirement.name)
            valid = tuple(dict.fromkeys(path for path in paths if _valid_artifact(path, kind, mission.title)))
            satisfied = bool(valid)
            rendered_not_approved = not satisfied and any(
                _artifact_file_exists(path, kind) for path in paths
            )
            statuses.append(RequirementStatus(requirement, satisfied, valid, rendered_not_approved))
        elif requirement.kind == "youtube_evidence":
            media_task = next((task for task in mission.tasks if task.agent == "media"), None)
            report = media_task.metadata.get("youtube_production") if media_task and media_task.metadata else None
            artifact = (report or {}).get("artifact", {}) if isinstance(report, dict) else {}
            visual = (report or {}).get("visual", {}) if isinstance(report, dict) else {}
            audio = (report or {}).get("audio", {}) if isinstance(report, dict) else {}
            creative = (report or {}).get("creative", {}) if isinstance(report, dict) else {}
            quality = (report or {}).get("quality", {}) if isinstance(report, dict) else {}
            mapping = {
                "youtube_opportunity_or_content_plan": bool(
                    (report and (creative.get("story_concept") or creative.get("script")))
                    or (media_task and media_task.metadata.get("youtube_content_plan") is True)
                ),
                "technical_validation": artifact.get("technical_validation") is True,
                "semantic_validation": artifact.get("semantic_validation") is True and quality.get("production_readiness") is True,
                "production_provenance": bool(artifact.get("production_provenance")),
                "story_coverage": len(creative.get("story_beats", [])) >= 4 and creative.get("scene_count", 0) >= 4,
                "motion_evidence": visual.get("body_motion") is True and (visual.get("body_motion_ratio") or 0) >= 1.8,
                "audio_evidence": audio.get("silence_detected") is False and audio.get("peak_db") is not None,
                "thumbnail_artifact_or_reasoned_not_required": bool(
                    artifact.get("thumbnail_path") and Path(artifact["thumbnail_path"]).is_file()
                ) or (report or {}).get("thumbnail", {}).get("not_required_reason") not in (None, ""),
                "youtube_learning_persisted": bool(media_task and media_task.status == TaskStatus.COMPLETED
                                                     and media_task.metadata.get("learning_persisted") is True),
                "learning_persisted": bool(media_task and media_task.status == TaskStatus.COMPLETED
                                             and media_task.metadata.get("learning_persisted") is True),
                "publish_not_used": not any((task.metadata or {}).get("publish_used") is True for task in mission.tasks),
            }
            statuses.append(RequirementStatus(requirement, bool(mapping.get(requirement.name))))
        elif requirement.kind == "finance_evidence":
            task = next((task for task in mission.tasks if task.agent == "finance"), None)
            report = task.metadata.get("report") if task is not None and task.metadata else None
            lab = (report or {}).get("strategy_lab") if isinstance(report, dict) else None
            candidates = (lab or {}).get("candidates", []) if isinstance(lab, dict) else []
            provenance_fields = {
                "name", "family", "source", "discovered_at", "baseline_or_new",
                "logic_summary", "parameters", "assets_tested", "regimes_tested",
            }
            novel = [item for item in candidates if item.get("baseline_or_new") == "new"]
            mapping = {
                "novel_strategy_candidates": bool(novel) and all(provenance_fields <= set(item) for item in novel),
                "multi_asset_evidence": len(set((lab or {}).get("assets_tested", []))) >= 2 and all(
                    len(set(item.get("assets_tested", []))) >= 2 for item in candidates
                ),
                "regime_evidence": len(set((lab or {}).get("regimes_tested", []))) >= 2 and all(
                    isinstance(item.get("regime_metrics"), dict) and len(item["regime_metrics"]) >= 2
                    for item in candidates
                ),
                "multi_timeframe_evidence": len(set((lab or {}).get("timeframes_tested", []))) >= 2 and all(
                    len(set(item.get("timeframes_tested", []))) >= 2 for item in candidates
                ),
                "strategy_research": len({item.get("family") for item in candidates if item.get("family")}) >= 2,
                "strategy_comparison": (lab or {}).get("strategy_count", 0) >= 2,
                "backtest": len(candidates) >= 2 and all("train_metrics" in item for item in candidates),
                "oos": bool(candidates) and all("out_of_sample_metrics" in item for item in candidates),
                "risk_performance": bool(candidates) and all(
                    all(key in item for key in ("net_return_after_costs", "max_drawdown", "win_rate", "profit_factor", "expectancy", "sharpe"))
                    for item in candidates
                ),
                "qualification": bool(candidates) and all(
                    isinstance(item.get("qualified"), bool)
                    and isinstance(item.get("qualification_reasons"), list)
                    for item in candidates
                ),
                # A qualified promotion OR an evidence-backed no-trade verdict
                # is a valid terminal decision. Merely saying PAPER is not.
                "paper_decision": (
                    (lab or {}).get("decision") == "PAPER CANDIDATE"
                    and bool((lab or {}).get("paper_promoted"))
                    and any(item.get("qualified") is True for item in candidates)
                ) or (
                    (lab or {}).get("decision") == "NO QUALIFIED STRATEGY"
                    and not (lab or {}).get("paper_promoted", False)
                    and bool(candidates)
                    and (
                        all(item.get("qualified") is False for item in candidates)
                        or (
                            (lab or {}).get("bounded_exploration_outcome") == "NO QUALIFIED STRATEGY AFTER BOUNDED EXPLORATION"
                            and bool(novel) and all(item.get("qualified") is False for item in novel)
                        )
                    )
                ),
                "market_data": bool((lab or {}).get("market_truth_source") is True
                                    or (lab or {}).get("source") == "Binance official OHLCV"
                                    or (report or {}).get("market_data_source")),
                "real_money_not_used": not any((item.metadata or {}).get("real_money_used") is True
                                                for item in mission.tasks),
            }
            if requirement.name == "learning_persisted":
                learning_task = next((item for item in mission.tasks if item.agent == "learning"), None)
                learning_report = learning_task.metadata.get("report") if learning_task and learning_task.metadata else None
                mapping["learning_persisted"] = bool(
                    learning_task and learning_task.status == TaskStatus.COMPLETED
                    and isinstance(learning_report, dict) and learning_report.get("learning_persisted") is True
                )
            statuses.append(RequirementStatus(requirement, bool(mapping.get(requirement.name))))
        else:
            task_agent = "github" if requirement.name == "readme" else requirement.name
            task = next((task for task in mission.tasks if task.agent == task_agent), None)
            report = task.metadata.get("report") if task is not None and task.metadata else None
            if requirement.name == "github":
                satisfied = bool(task and task.status == TaskStatus.COMPLETED and (report or {}).get("top"))
            elif requirement.name == "readme":
                satisfied = bool(task and task.status == TaskStatus.COMPLETED and (report or {}).get("readme_summary"))
            else:
                satisfied = bool(task and task.status == TaskStatus.COMPLETED and _has_evidence(report))
            statuses.append(RequirementStatus(requirement, satisfied))
    return GoalCompletion(tuple(statuses))


def domain_completion(mission) -> dict[str, dict]:
    """Evidence-derived subgoal state; task counts are not goal completion."""
    grouped: dict[str, list[RequirementStatus]] = {}
    for item in evaluate_goal_completion(mission).requirements:
        grouped.setdefault(item.requirement.domain, []).append(item)
    result = {}
    for domain, items in grouped.items():
        present = sum(item.satisfied for item in items)
        result[domain] = {
            "status": "COMPLETE" if present == len(items) else "INCOMPLETE",
            "progress": round(100.0 * present / len(items), 1) if items else 0.0,
            "evidence": {item.requirement.name: "PRESENT" if item.satisfied else "MISSING" for item in items},
        }
    return result


def evidence_progress(mission, fallback: float = 0.0) -> float:
    completion = evaluate_goal_completion(mission)
    if not completion.requirements:
        return fallback
    return round(100.0 * sum(item.satisfied for item in completion.requirements) / len(completion.requirements), 1)


def collect_valid_artifact_paths(mission) -> list[str]:
    """Return verified artifacts and bridge task metadata to mission state."""
    valid: list[str] = []
    for raw_path in _reported_paths(mission):
        cleaned = raw_path.strip().strip("'\"")
        suffix = Path(cleaned).suffix.casefold()
        kind = next(
            (candidate for candidate, extensions in ARTIFACT_EXTENSIONS.items() if suffix in extensions),
            None,
        )
        if kind is not None and _valid_artifact(cleaned, kind, mission.title) and cleaned not in valid:
            valid.append(cleaned)
    return valid


def _reported_paths(mission) -> Iterable[str]:
    for value in getattr(mission, "artifact_paths", ()) or ():
        yield str(value)
    for task in mission.tasks:
        metadata = task.metadata or {}
        for key in _PATH_METADATA_KEYS:
            if key in metadata:
                yield from _flatten_paths(metadata[key])
        if task.result is not None:
            yield from _paths_in_text(str(task.result.output))


def _flatten_paths(value) -> Iterable[str]:
    if isinstance(value, (str, Path)):
        yield str(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _flatten_paths(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _flatten_paths(item)


def _paths_in_text(text: str) -> Iterable[str]:
    extensions = sorted({ext for values in ARTIFACT_EXTENSIONS.values() for ext in values}, key=len, reverse=True)
    pattern = rf"(?im)(?:^|[\s:'\"])([^\r\n<>|?*\"]+?(?:{'|'.join(re.escape(ext) for ext in extensions)}))(?=$|[\s'\"])"
    for match in re.finditer(pattern, text or ""):
        yield match.group(1).strip()


def _artifact_file_exists(raw_path: str, kind: ArtifactType) -> bool:
    """True when a real, non-empty file of the right extension exists on
    disk for this artifact kind -- regardless of whether it PASSED semantic
    quality validation. This is the ``rendered_not_approved`` signal's
    truth source (round 4 repair): it lets callers distinguish "no
    artifact was ever produced" from "a real artifact exists but quality
    validation has not approved it (yet, or at all)"."""
    path = Path(raw_path.strip().strip("'\""))
    if path.suffix.casefold() not in ARTIFACT_EXTENSIONS[kind]:
        return False
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _valid_artifact(raw_path: str, kind: ArtifactType, goal: str = "") -> bool:
    path = Path(raw_path.strip().strip("'\""))
    if path.suffix.casefold() not in ARTIFACT_EXTENSIONS[kind]:
        return False
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        if kind == ArtifactType.VIDEO:
            from src.media.quality import validate_media_goal_artifact
            return validate_media_goal_artifact(path, goal).passed
        return True
    except OSError:
        return False


def _has_evidence(report) -> bool:
    if not isinstance(report, dict) or not report:
        return False
    meaningful = {
        key: value for key, value in report.items()
        if key not in {"duration_seconds", "category"} and value not in (None, "", [], {}, ())
    }
    return bool(meaningful)
