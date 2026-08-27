from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Any

from src.capabilities.capability_registry import CapabilityRegistry
from src.capabilities.requirement import (
    CODE_GENERATION,
    DETERMINISTIC_VIDEO_RENDER,
    REASONING,
    SCRIPT_GENERATION,
    WEB_RESEARCH,
    CapabilityRequirement,
)
from src.media.capability_model import MEDIA_CAPABILITIES, VIDEO_RENDER
from src.media.provider_selection import provider_health, rank_available_providers
from src.providers.cost_optimizer import TASK_COST_PROFILES, TASK_CODING, TASK_PLANNING, TASK_RESEARCH, CostOptimizer
from src.providers.execution_history import ProviderExecutionHistory
from src.providers.provider_manager import ProviderManager

# Sprint: generic capability-requirement resolution. This module NEVER
# performs a network/GitHub call, NEVER installs/executes anything, and
# NEVER auto-approves anything -- it only reads state already produced by
# the existing pipelines (src.media.provider_selection,
# src.providers.provider_manager/cost_optimizer/execution_history,
# src.capabilities.capability_registry, src.research_loop.autonomous) and,
# at most, registers a metadata-only research topic for the EXISTING
# scheduled/manual discovery cycle to act on later, under its own
# approval gates. No second selection/discovery/approval system is
# introduced here.

READY = "READY"
DEGRADED = "DEGRADED"
DISCOVERING = "DISCOVERING"
APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
HARDWARE_INCOMPATIBLE = "HARDWARE_INCOMPATIBLE"
AUTH_REQUIRED = "AUTH_REQUIRED"
QUOTA_BLOCKED = "QUOTA_BLOCKED"
CAPABILITY_GAP = "CAPABILITY_GAP"

# Priority used to pick the single most informative status when multiple
# sources were tried and none resolved READY/DEGRADED -- more specific,
# more actionable statuses win over the generic CAPABILITY_GAP.
_STATUS_PRIORITY = (
    APPROVAL_REQUIRED, AUTH_REQUIRED, QUOTA_BLOCKED, HARDWARE_INCOMPATIBLE, DISCOVERING, CAPABILITY_GAP,
)

# Reuses the SAME priority/fallback tables ProviderManager/CostOptimizer
# already use for text-task routing -- no second provider-selection table.
_TEXT_CAPABILITY_TASK_TYPES: dict[str, str] = {
    WEB_RESEARCH: TASK_RESEARCH,
    REASONING: TASK_PLANNING,
    SCRIPT_GENERATION: TASK_PLANNING,
    CODE_GENERATION: TASK_CODING,
}

_LOCAL_RENDER_CAPABILITIES = frozenset({DETERMINISTIC_VIDEO_RENDER, VIDEO_RENDER})

_QUOTA_MARKERS = ("top_up", "top-up", "quota", "locked", "insufficient balance", "insufficient credit")
_AUTH_MARKERS = ("api key", "api_key", "not configured", "not set", "unauthorized", "auth")


@dataclass(frozen=True)
class CapabilityResolution:
    capability: str
    status: str
    resolved_by: str = ""
    cost_class: str = "unknown"
    health: str = "unknown"
    source: str = "none"
    reason: str = ""
    candidates_considered: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def gap(self) -> bool:
        return self.status not in (READY, DEGRADED)

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability, "status": self.status, "resolved_by": self.resolved_by,
            "cost_class": self.cost_class, "health": self.health, "source": self.source,
            "reason": self.reason, "candidates_considered": list(self.candidates_considered),
        }


def _local_render_resolution(name: str) -> CapabilityResolution:
    """Local ffmpeg-based compositing (src.media.renderer) -- not a remote
    provider; a hardware/tool presence check, not a second selection
    system."""
    available = bool(shutil.which("ffmpeg"))
    return CapabilityResolution(
        capability=name, status=READY if available else CAPABILITY_GAP,
        resolved_by="ffmpeg" if available else "", cost_class="free", health="HEALTHY" if available else "unknown",
        source="local_renderer",
        reason="ffmpeg is present locally." if available else "ffmpeg was not found on PATH.",
        candidates_considered=({"provider_id": "ffmpeg", "selectable": available,
                                 "reason": "local binary presence via shutil.which"},),
    )


def _media_resolution(name: str, *, history: ProviderExecutionHistory, quality_required: bool) -> CapabilityResolution | None:
    if name not in MEDIA_CAPABILITIES:
        return None
    eligible, considered = rank_available_providers(name, quality_required=quality_required, history=history)
    considered_dicts = tuple({
        "provider_id": item.profile.provider_id, "model_id": item.profile.model_id,
        "selectable": item.selectable, "reason": item.reason,
    } for item in considered)
    if not eligible:
        status = CAPABILITY_GAP
        lowered = " ".join(c.reason.casefold() for c in considered)
        if any(marker in lowered for marker in _QUOTA_MARKERS):
            status = QUOTA_BLOCKED
        elif any(marker in lowered for marker in _AUTH_MARKERS):
            status = AUTH_REQUIRED
        return CapabilityResolution(
            capability=name, status=status, source="media_provider",
            reason=f"No genuinely available media provider supports {name!r}.",
            candidates_considered=considered_dicts,
        )
    profile, _provider = eligible[0]
    health = provider_health(profile.provider_id, name, history)
    return CapabilityResolution(
        capability=name, status=READY if health.status == "HEALTHY" else DEGRADED,
        resolved_by=f"{profile.provider_id}/{profile.model_id}", cost_class=profile.cost_class,
        health=health.status, source="media_provider",
        reason=f"Selected {profile.provider_id}/{profile.model_id} for {name!r}.",
        candidates_considered=considered_dicts,
    )


def _text_provider_resolution(
    name: str, *, history: ProviderExecutionHistory, provider_manager: ProviderManager,
) -> CapabilityResolution | None:
    task_type = _TEXT_CAPABILITY_TASK_TYPES.get(name)
    if task_type is None:
        return None
    profile = TASK_COST_PROFILES.get(task_type)
    ordered = [p for p in (profile.priority_provider, profile.fallback_provider) if p] if profile else []
    considered: list[dict[str, Any]] = []
    healthy: tuple[str, Any] | None = None
    fallback: tuple[str, Any] | None = None
    for provider_name in dict.fromkeys(ordered):
        candidate = provider_manager.get(provider_name)
        available = bool(candidate and candidate.is_available())
        if not available:
            considered.append({"provider_id": provider_name, "selectable": False,
                                "reason": "not configured/available for this task type"})
            continue
        health = provider_health(provider_name, name, history)
        considered.append({"provider_id": provider_name, "selectable": True,
                            "reason": f"eligible ({health.status.lower()})"})
        if health.status == "HEALTHY" and healthy is None:
            healthy = (provider_name, health)
        elif fallback is None:
            # Kept only in case no candidate anywhere in the priority list
            # is currently healthy -- a healthy candidate found later in the
            # loop still wins (see below).
            fallback = (provider_name, health)
    chosen = healthy or fallback
    if chosen is None:
        return CapabilityResolution(
            capability=name, status=CAPABILITY_GAP, source="text_provider",
            reason=f"No configured/available text provider supports {name!r} (task_type={task_type}).",
            candidates_considered=tuple(considered),
        )
    provider_name, chosen_health = chosen
    cost_class = CostOptimizer.cost_class(provider_name)
    return CapabilityResolution(
        capability=name, status=READY if chosen_health.status == "HEALTHY" else DEGRADED,
        resolved_by=provider_name, cost_class=cost_class, health=chosen_health.status, source="text_provider",
        reason=f"Selected {provider_name!r} for {name!r} (task_type={task_type}).",
        candidates_considered=tuple(considered),
    )


def _registry_resolution(name: str, *, capability_registry: CapabilityRegistry) -> CapabilityResolution | None:
    rows = capability_registry.select(name)
    if not rows:
        return None
    row = rows[0]
    row_id = row.id if hasattr(row, "id") else row.get("capability_id")
    return CapabilityResolution(
        capability=name, status=READY, resolved_by=str(row_id or ""), cost_class="unknown",
        health="HEALTHY", source="capability_registry",
        reason=f"Already-integrated capability {row_id!r} satisfies {name!r}.",
        candidates_considered=({"provider_id": str(row_id or ""), "selectable": True,
                                 "reason": "active, verified capability registry entry"},),
    )


def _matches_capability(row: dict[str, Any], name: str) -> bool:
    values = {row.get("capability_id"), row.get("category"), *(row.get("provides_capabilities") or [])}
    return name in values


def _in_flight_resolution(name: str, *, capability_registry: CapabilityRegistry) -> CapabilityResolution | None:
    """Truthfully report a capability already somewhere in the existing
    discovery/evaluation/approval pipeline (System A -- src.capabilities +
    src.research_loop.autonomous) -- reads only, never advances the state
    machine itself."""
    store = capability_registry.store
    if store is None:
        return None
    research = store.snapshot().get("autonomous_research", {})
    tools = [row for row in research.get("tools", []) if _matches_capability(row, name)]
    if not tools:
        return None
    row = tools[-1]
    status = str(row.get("status") or "")
    evaluation = next(
        (e for e in reversed(research.get("evaluations", []))
         if e.get("capability_id") == row.get("capability_id") and e.get("current")), None,
    )
    reason = f"Candidate {row.get('repository') or row.get('name')!r} is in state {status!r}."
    # Hardware incompatibility is checked first: it is more specific,
    # actionable evidence than a generic pending-approval status, and the
    # existing evaluator (src.capabilities.capability_evaluator) already
    # conservatively marks CUDA/GPU-required-but-unprovable candidates this
    # way regardless of which lifecycle stage the row currently sits at.
    if (evaluation is not None
          and evaluation.get("jarvis_environment_compatibility") == "UNKNOWN"
          and evaluation.get("runtime_requirements", {}).get("cuda") == "REQUIRED"):
        resolved_status = HARDWARE_INCOMPATIBLE
        reason = (f"Candidate {row.get('repository') or row.get('name')!r} requires CUDA/GPU that cannot be "
                  "verified on this machine.")
    elif evaluation is not None and (evaluation.get("requires_api_key") is True or evaluation.get("requires_account") is True):
        resolved_status = AUTH_REQUIRED
        reason = f"Candidate {row.get('repository') or row.get('name')!r} requires credentials not yet configured."
    elif "APPROVAL_REQUIRED" in status:
        resolved_status = APPROVAL_REQUIRED
    elif status in {"ACTIVE_CAPABILITY"}:
        return None  # would already have been found by _registry_resolution
    else:
        resolved_status = DISCOVERING
    return CapabilityResolution(
        capability=name, status=resolved_status, source="capability_registry", reason=reason,
        candidates_considered=({"provider_id": str(row.get("capability_id") or ""), "selectable": False,
                                 "reason": reason},),
    )


def _discovery_topic_resolution(name: str, *, capability_registry: CapabilityRegistry) -> CapabilityResolution:
    store = capability_registry.store
    if store is None:
        return CapabilityResolution(
            capability=name, status=CAPABILITY_GAP, source="none",
            reason=f"No provider, registry entry, or in-flight candidate satisfies {name!r}; no store available to register discovery.",
        )
    tag = f"capability:{name}"
    research = store.snapshot().get("autonomous_research", {})
    existing = next((t for t in research.get("topics", []) if tag in (t.get("tags") or [])), None)
    if existing is not None:
        return CapabilityResolution(
            capability=name, status=DISCOVERING, source="none",
            reason=f"Discovery topic {existing.get('name')!r} already registered and pending its next cycle.",
        )
    from src.research_loop.autonomous import AutonomousResearchService
    topic = AutonomousResearchService(store=store).create_topic(
        name=f"capability discovery: {name}",
        description=f"Bounded discovery for the missing JARVIS capability {name!r}.",
        tags=[tag], source_preferences=["GITHUB", "OFFICIAL_DOCS"],
    )
    return CapabilityResolution(
        capability=name, status=DISCOVERING, source="none",
        reason=f"Registered discovery topic {topic.get('name')!r}; no candidate exists yet.",
    )


def resolve_capability_name(
    name: str, *, history: ProviderExecutionHistory | None = None,
    capability_registry: CapabilityRegistry | None = None, provider_manager: ProviderManager | None = None,
    quality_required: bool = False, allow_discovery_topic: bool = True,
) -> CapabilityResolution:
    """Resolve a single capability name, trying every genuinely applicable
    existing source in priority order and only falling through when a
    source is inapplicable or fails to resolve READY/DEGRADED."""

    history = history or ProviderExecutionHistory()
    capability_registry = capability_registry or CapabilityRegistry()
    provider_manager = provider_manager or ProviderManager()

    attempts: list[CapabilityResolution] = []

    if name in _LOCAL_RENDER_CAPABILITIES:
        attempts.append(_local_render_resolution(name))
        if attempts[-1].status in (READY, DEGRADED):
            return attempts[-1]

    media = _media_resolution(name, history=history, quality_required=quality_required)
    if media is not None:
        attempts.append(media)
        if media.status in (READY, DEGRADED):
            return media

    text = _text_provider_resolution(name, history=history, provider_manager=provider_manager)
    if text is not None:
        attempts.append(text)
        if text.status in (READY, DEGRADED):
            return text

    registry = _registry_resolution(name, capability_registry=capability_registry)
    if registry is not None:
        attempts.append(registry)
        if registry.status in (READY, DEGRADED):
            return registry

    in_flight = _in_flight_resolution(name, capability_registry=capability_registry)
    if in_flight is not None:
        attempts.append(in_flight)

    if not attempts or all(a.status == CAPABILITY_GAP for a in attempts):
        if allow_discovery_topic:
            attempts.append(_discovery_topic_resolution(name, capability_registry=capability_registry))
        elif not attempts:
            attempts.append(CapabilityResolution(
                capability=name, status=CAPABILITY_GAP, source="none",
                reason=f"No provider, registry entry, or in-flight candidate satisfies {name!r}.",
            ))

    best_status = next((s for s in _STATUS_PRIORITY if any(a.status == s for a in attempts)), CAPABILITY_GAP)
    chosen = next(a for a in attempts if a.status == best_status)
    all_candidates = tuple(c for a in attempts for c in a.candidates_considered)
    return CapabilityResolution(
        capability=name, status=chosen.status, resolved_by=chosen.resolved_by, cost_class=chosen.cost_class,
        health=chosen.health, source=chosen.source, reason=chosen.reason, candidates_considered=all_candidates,
    )


def resolve_capability_requirement(
    requirement: CapabilityRequirement, *, history: ProviderExecutionHistory | None = None,
    capability_registry: CapabilityRegistry | None = None, provider_manager: ProviderManager | None = None,
    quality_required: bool = False, allow_discovery_topic: bool = True,
) -> CapabilityResolution:
    """Try each alternative group in declared order; the first group whose
    every member resolves READY/DEGRADED wins. If none does, the single
    most informative attempted resolution (across all groups/names) is
    returned so CAPABILITY_GAP evidence stays truthful."""

    kwargs = dict(history=history, capability_registry=capability_registry, provider_manager=provider_manager,
                   quality_required=quality_required, allow_discovery_topic=allow_discovery_topic)
    all_attempts: list[CapabilityResolution] = []
    for group in requirement.alternatives:
        group_results = [resolve_capability_name(name, **kwargs) for name in group]
        all_attempts.extend(group_results)
        if all(r.status in (READY, DEGRADED) for r in group_results):
            # DEGRADED outranks READY here: the group's overall status must
            # reflect its weakest member, not its strongest.
            worst = max(group_results, key=lambda r: 0 if r.status == READY else 1)
            resolved_by = ", ".join(r.resolved_by for r in group_results if r.resolved_by)
            cost_classes = {r.cost_class for r in group_results}
            return CapabilityResolution(
                capability=requirement.name, status=worst.status, resolved_by=resolved_by,
                cost_class=cost_classes.pop() if len(cost_classes) == 1 else "mixed",
                health=worst.health, source=worst.source,
                reason=f"Satisfied {requirement.name!r} via {group!r} ({resolved_by}).",
                candidates_considered=tuple(c for r in group_results for c in r.candidates_considered),
            )

    best_status = next((s for s in _STATUS_PRIORITY if any(a.status == s for a in all_attempts)), CAPABILITY_GAP)
    chosen = next((a for a in all_attempts if a.status == best_status), None)
    all_candidates = tuple(c for a in all_attempts for c in a.candidates_considered)
    if chosen is None:
        return CapabilityResolution(capability=requirement.name, status=CAPABILITY_GAP,
                                     reason=f"No alternative satisfies {requirement.name!r}.")
    return CapabilityResolution(
        capability=requirement.name, status=chosen.status, resolved_by=chosen.resolved_by,
        cost_class=chosen.cost_class, health=chosen.health, source=chosen.source,
        reason=f"No alternative fully resolved for {requirement.name!r}; closest: {chosen.reason}",
        candidates_considered=all_candidates,
    )


def resolve_capability_plan(
    requirements: tuple[CapabilityRequirement, ...], **kwargs: Any,
) -> tuple[CapabilityResolution, ...]:
    return tuple(resolve_capability_requirement(requirement, **kwargs) for requirement in requirements)
