from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.config.settings import Settings
from src.media.capability_model import MediaModelProfile
from src.providers.aiml_media_provider import AIMLMediaProvider
from src.providers.execution_history import ProviderExecutionHistory
from src.providers.fal_provider import FalMediaProvider
from src.providers.ltx_provider import LTXMediaProvider
from src.providers.media_provider_base import MediaProvider
from src.providers.nvidia_provider import NvidiaMediaProvider

# Sprint: multi-provider media capability foundation -- dynamic, per-
# capability provider/model ranking. This is NOT a second ProviderManager:
# it is one small, stateless selection function over the SAME small set of
# MediaProvider instances (below), reusing ProviderExecutionHistory (task
# type = the media capability string, e.g. "text_to_image") for reliability
# and CostOptimizer.cost_class() (via each provider's profile()) for cost
# ranking. Extend this tuple to add a new media provider; nothing else in
# this module hardcodes "nvidia"/"ltx"/"fal"/"aiml" by name.
_PROVIDERS: tuple[MediaProvider, ...] = (
    NvidiaMediaProvider(), FalMediaProvider(), LTXMediaProvider(), AIMLMediaProvider(),
)

_COST_RANK = {"free": 0, "plan": 0, "unknown": 2, "paid": 3}

# Bounded, auto-recovering provider health/cooldown -- distinct from
# MediaModelProfile.availability (which only reflects configured auth/
# hardware state, e.g. "NVIDIA_API_KEY is set"). A provider can be
# genuinely AVAILABLE (valid key) while its hosted endpoint is actually
# timing out/500ing right now -- COOLDOWN_FAILURE_THRESHOLD consecutive
# recent failures for a (provider, capability) pair deprioritize it in
# ranking (never exclude it outright -- a lone remaining candidate stays
# selectable, so truthful CAPABILITY_GAP is preserved) for
# MEDIA_PROVIDER_COOLDOWN_SECONDS. Any subsequent recorded success, or the
# window elapsing, restores it -- never a permanent blacklist.
_COOLDOWN_LOOKBACK = 5
_COOLDOWN_FAILURE_THRESHOLD = 3


@dataclass(frozen=True)
class ProviderHealth:
    status: str  # "HEALTHY" | "COOLDOWN"
    reason: str
    cooldown_until: str | None = None


def provider_health(provider_id: str, capability: str, history: ProviderExecutionHistory) -> ProviderHealth:
    """Real-execution-history-derived health for one (provider, capability)
    pair. See module docstring above for the policy this implements."""
    recent = history.recent_for(provider_id, capability, limit=_COOLDOWN_LOOKBACK)
    if not recent:
        return ProviderHealth("HEALTHY", "no recent execution history")

    consecutive_failures = 0
    for entry in recent:  # most-recent-first
        if entry.get("success"):
            break
        consecutive_failures += 1

    if consecutive_failures < _COOLDOWN_FAILURE_THRESHOLD:
        return ProviderHealth(
            "HEALTHY",
            f"{consecutive_failures} consecutive recent failure(s) for {provider_id}/{capability} "
            f"(below cooldown threshold of {_COOLDOWN_FAILURE_THRESHOLD})",
        )

    last_failure_at = str(recent[0].get("recorded_at") or "")
    try:
        last_time = datetime.fromisoformat(last_failure_at)
    except ValueError:
        return ProviderHealth("HEALTHY", "recent failures recorded but timestamp unavailable; cooldown not applied")

    cooldown_until = last_time + timedelta(seconds=Settings.MEDIA_PROVIDER_COOLDOWN_SECONDS)
    if datetime.now() >= cooldown_until:
        return ProviderHealth("HEALTHY", f"cooldown window elapsed since last failure at {last_failure_at}")

    return ProviderHealth(
        "COOLDOWN",
        f"{consecutive_failures} consecutive recent failures for {provider_id}/{capability} "
        f"(last at {last_failure_at}); deprioritized until {cooldown_until.isoformat(timespec='seconds')}",
        cooldown_until=cooldown_until.isoformat(timespec="seconds"),
    )


@dataclass(frozen=True)
class CandidateEvaluation:
    """One considered (provider, model) pairing and why it was/wasn't
    selectable -- CAPABILITY_GAP evidence must be able to cite this."""

    profile: MediaModelProfile
    selectable: bool
    reason: str


@dataclass(frozen=True)
class MediaSelectionResult:
    capability: str
    selected: MediaModelProfile | None
    provider: MediaProvider | None
    reason: str
    candidates_considered: tuple[CandidateEvaluation, ...] = field(default_factory=tuple)

    @property
    def gap(self) -> bool:
        return self.selected is None


def _score(profile: MediaModelProfile, history: ProviderExecutionHistory, capability: str,
           *, quality_required: bool) -> tuple:
    """Lower sorts first. Mandatory filters (capability match, availability)
    already applied by the caller -- this only RANKS already-eligible
    candidates, per the required policy order: recent health/cooldown beats
    everything else (a currently-failing provider should not keep winning
    just because it's free/high-quality), then quality (if required) beats
    cost; otherwise free/local/plan is preferred over paid, then quality,
    then speed, then recent reliability."""

    health_rank = 1 if provider_health(profile.provider_id, capability, history).status == "COOLDOWN" else 0
    success_rate = history.success_rate(profile.provider_id, capability)
    reliability_rank = -(success_rate if success_rate is not None else 50.0)
    cost_rank = _COST_RANK.get(profile.cost_class, 2)
    if quality_required:
        # Quality requirement can justify a paid provider beating a free one
        # (Phase 6 requirement H) -- quality dominates cost in the sort key.
        return (health_rank, -profile.quality_tier, cost_rank, -profile.speed_tier, reliability_rank)
    return (health_rank, cost_rank, -profile.quality_tier, -profile.speed_tier, reliability_rank)


def rank_available_providers(
    capability: str, *, quality_required: bool = False,
    require_vertical_video: bool = False, require_image_conditioning: bool = False,
    history: ProviderExecutionHistory | None = None,
) -> tuple[list[tuple[MediaModelProfile, MediaProvider]], tuple[CandidateEvaluation, ...]]:
    """Every genuinely eligible (profile, provider) pair, best first, plus
    the full considered list (including rejected candidates) for truthful
    CAPABILITY_GAP evidence. The ranked list lets a caller bounded-retry the
    NEXT candidate when the top choice's actual generation call fails
    (Phase 8: quality/execution-driven fallback), not just at selection
    time.
    """
    history = history or ProviderExecutionHistory()
    considered: list[CandidateEvaluation] = []
    eligible: list[tuple[MediaModelProfile, MediaProvider]] = []

    for provider in _PROVIDERS:
        for profile in provider.profiles():
            if capability not in profile.capabilities:
                considered.append(CandidateEvaluation(profile, False,
                    f"{profile.provider_id}/{profile.model_id} does not support {capability!r}"))
                continue
            if not profile.availability:
                considered.append(CandidateEvaluation(profile, False,
                    f"{profile.provider_id}/{profile.model_id} unavailable: {profile.unavailable_reason}"))
                continue
            if require_vertical_video and not profile.supports_vertical_video:
                considered.append(CandidateEvaluation(profile, False,
                    f"{profile.provider_id}/{profile.model_id} does not support vertical video"))
                continue
            if require_image_conditioning and not profile.supports_image_conditioning:
                considered.append(CandidateEvaluation(profile, False,
                    f"{profile.provider_id}/{profile.model_id} does not support image conditioning"))
                continue
            health = provider_health(profile.provider_id, capability, history)
            reason = "eligible" if health.status == "HEALTHY" else f"eligible but recently unhealthy: {health.reason}"
            considered.append(CandidateEvaluation(profile, True, reason))
            eligible.append((profile, provider))

    eligible.sort(key=lambda pair: _score(pair[0], history, capability, quality_required=quality_required))
    return eligible, tuple(considered)


def select_media_provider(
    capability: str, *, quality_required: bool = False,
    require_vertical_video: bool = False, require_image_conditioning: bool = False,
    history: ProviderExecutionHistory | None = None,
) -> MediaSelectionResult:
    """Rank every genuinely available, capability-matching provider/model
    and return the best one -- or, if none qualify, a truthful gap result
    carrying every candidate considered and why it was rejected (auth
    missing, capability mismatch, unmet constraint). Never fabricates a
    selection to avoid a gap.
    """
    eligible, considered = rank_available_providers(
        capability, quality_required=quality_required, require_vertical_video=require_vertical_video,
        require_image_conditioning=require_image_conditioning, history=history)

    if not eligible:
        return MediaSelectionResult(capability, None, None,
            reason=f"No genuinely available provider supports {capability!r}.",
            candidates_considered=considered)

    best_profile, best_provider = eligible[0]
    reason = (f"Selected {best_profile.provider_id}/{best_profile.model_id} for {capability!r} "
              f"(cost_class={best_profile.cost_class}, quality_tier={best_profile.quality_tier}"
              f"{', quality-required override' if quality_required else ''}).")
    return MediaSelectionResult(capability, best_profile, best_provider, reason,
                                 candidates_considered=considered)
