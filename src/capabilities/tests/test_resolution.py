from __future__ import annotations

from src.capabilities.capability_registry import CapabilityRegistry
from src.capabilities.requirement import CapabilityRequirement, OPTIONAL, REQUIRED, WEB_RESEARCH
from src.capabilities.resolution import (
    AUTH_REQUIRED,
    CAPABILITY_GAP,
    DEGRADED,
    DISCOVERING,
    READY,
    resolve_capability_name,
    resolve_capability_plan,
)
from src.control_center.store import ControlCenterStore
from src.media.capability_model import MediaModelProfile
from src.media.provider_selection import CandidateEvaluation
from src.providers.execution_history import ProviderExecutionHistory


def _history(tmp_path, monkeypatch) -> ProviderExecutionHistory:
    monkeypatch.chdir(tmp_path)
    return ProviderExecutionHistory()


class _FakeProvider:
    def __init__(self, available: bool) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available


class _FakeProviderManager:
    def __init__(self, available: dict[str, bool]) -> None:
        self._available = available

    def get(self, name: str):
        if name not in self._available:
            return None
        return _FakeProvider(self._available[name])


# B: an operational text capability resolves without any discovery/topic.
def test_operational_text_capability_resolves_without_discovery(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)
    store = ControlCenterStore(tmp_path / "s.json")
    registry = CapabilityRegistry(store=store)
    manager = _FakeProviderManager({"gemini": True, "openrouter": True})

    result = resolve_capability_name(
        WEB_RESEARCH, history=history, capability_registry=registry, provider_manager=manager,
    )

    assert result.status == READY
    assert result.resolved_by == "gemini"  # TASK_RESEARCH priority_provider
    assert store.snapshot()["autonomous_research"]["topics"] == []


# C: a configured-but-cooldown provider is not treated as equivalent to a
# healthy one -- three consecutive recorded failures push it to DEGRADED.
def test_cooldown_provider_is_degraded_not_ready(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)
    for _ in range(3):
        history.record(task_type=WEB_RESEARCH, provider="gemini", success=False, fallback_used=False, duration_seconds=1.0)
    manager = _FakeProviderManager({"gemini": True})  # fallback ("openrouter") unavailable

    result = resolve_capability_name(WEB_RESEARCH, history=history, provider_manager=manager)

    assert result.status == DEGRADED
    assert result.resolved_by == "gemini"


def test_healthy_fallback_beats_cooldown_priority(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)
    for _ in range(3):
        history.record(task_type=WEB_RESEARCH, provider="gemini", success=False, fallback_used=False, duration_seconds=1.0)
    manager = _FakeProviderManager({"gemini": True, "openrouter": True})

    result = resolve_capability_name(WEB_RESEARCH, history=history, provider_manager=manager)

    assert result.status == READY
    assert result.resolved_by == "openrouter"


# E: an OPTIONAL requirement that cannot resolve must not read as blocking.
def test_optional_capability_gap_does_not_block_plan(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)
    manager = _FakeProviderManager({"gemini": True})
    plan = (
        CapabilityRequirement(WEB_RESEARCH, REQUIRED, ((WEB_RESEARCH,),)),
        CapabilityRequirement("nonexistent_extra", OPTIONAL, (("nonexistent_extra",),)),
    )

    resolutions = resolve_capability_plan(
        plan, history=history, provider_manager=manager, allow_discovery_topic=False,
    )

    by_name = {r.capability: r for r in resolutions}
    assert by_name["nonexistent_extra"].status == CAPABILITY_GAP
    blocking = [r for r, req in zip(resolutions, plan) if req.necessity == REQUIRED and r.gap]
    assert blocking == []  # only the REQUIRED entries would block a mission


# G: a registry candidate that is merely open-source/discovered (not yet
# ACTIVE_CAPABILITY) must not be reported as READY/available.
def test_in_flight_open_source_candidate_is_not_available(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)
    store = ControlCenterStore(tmp_path / "s.json")
    store.update(lambda s: s["autonomous_research"]["tools"].append({
        "capability_id": "cap-1", "category": "some_open_source_tool", "status": "EVALUATED_CANDIDATE",
        "repository": "acme/tool",
    }))
    store.update(lambda s: s["autonomous_research"]["evaluations"].append({
        "capability_id": "cap-1", "current": True,
        "license": {"detected": True, "license_name": "MIT"},
        "jarvis_environment_compatibility": "PARTIAL",
        "runtime_requirements": {"cuda": "UNKNOWN"},
    }))
    registry = CapabilityRegistry(store=store)
    manager = _FakeProviderManager({})

    result = resolve_capability_name(
        "some_open_source_tool", history=history, capability_registry=registry, provider_manager=manager,
        allow_discovery_topic=False,
    )

    assert result.status == DISCOVERING
    assert result.status != READY


# H: an already-healthy, already-configured provider wins over triggering
# new discovery -- no topic should ever be registered when a working source
# is found first.
def test_healthy_existing_provider_prevents_unnecessary_discovery(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)
    store = ControlCenterStore(tmp_path / "s.json")
    registry = CapabilityRegistry(store=store)
    manager = _FakeProviderManager({"gemini": True})

    result = resolve_capability_name(
        WEB_RESEARCH, history=history, capability_registry=registry, provider_manager=manager,
        allow_discovery_topic=True,
    )

    assert result.status == READY
    assert store.snapshot()["autonomous_research"]["topics"] == []


# I: a media capability whose only path needs unconfigured credentials must
# come back AUTH_REQUIRED, never silently resolved.
def test_media_capability_requiring_new_key_is_auth_required(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)

    def fake_rank(name, *, quality_required=False, require_vertical_video=False,
                  require_image_conditioning=False, history=None):
        profile = MediaModelProfile(
            provider_id="fake_media", model_id="fake-model", capabilities=(name,), availability=False,
            auth_required=True, cost_class="paid", free_tier=False, subscription_cli=False,
            local_or_remote="remote", quality_tier=80, speed_tier=80,
            unavailable_reason="FAKE_MEDIA_API_KEY is not configured.",
        )
        considered = (CandidateEvaluation(profile, False, f"{profile.provider_id}/{profile.model_id} unavailable: "
                                                            f"{profile.unavailable_reason}"),)
        return [], considered

    monkeypatch.setattr("src.capabilities.resolution.rank_available_providers", fake_rank)

    from src.media.capability_model import TEXT_TO_IMAGE
    result = resolve_capability_name(TEXT_TO_IMAGE, history=history, allow_discovery_topic=False)

    assert result.status == AUTH_REQUIRED


# N/O: a known-good resolution is reused unchanged while health is
# unchanged, and is re-evaluated (not blindly repeated) the moment health
# changes -- both for free via provider_health's existing cooldown, no new
# staleness/caching layer.
def test_known_good_resolution_reused_until_health_changes(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)
    manager = _FakeProviderManager({"gemini": True})

    first = resolve_capability_name(WEB_RESEARCH, history=history, provider_manager=manager)
    second = resolve_capability_name(WEB_RESEARCH, history=history, provider_manager=manager)
    assert first.status == READY and second.status == READY
    assert first.resolved_by == second.resolved_by == "gemini"  # N: unchanged health -> same resolution, no rediscovery

    for _ in range(3):
        history.record(task_type=WEB_RESEARCH, provider="gemini", success=False, fallback_used=False, duration_seconds=1.0)
    third = resolve_capability_name(WEB_RESEARCH, history=history, provider_manager=manager)
    assert third.status == DEGRADED  # O: health changed -> re-evaluated, not blindly repeated as READY


# J: nothing resolves anywhere -> truthful CAPABILITY_GAP with a clear
# reason, never a fabricated selection.
def test_nothing_resolves_returns_truthful_capability_gap(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)
    manager = _FakeProviderManager({})

    result = resolve_capability_name(
        "totally_unmodeled_capability", history=history, provider_manager=manager, allow_discovery_topic=False,
    )

    assert result.status == CAPABILITY_GAP
    assert "totally_unmodeled_capability" in result.reason
