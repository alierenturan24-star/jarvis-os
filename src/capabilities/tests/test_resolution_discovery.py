from __future__ import annotations

import copy

from src.capabilities.capability_evaluator import PassiveCapabilityEvaluator, RepositoryEvidence
from src.capabilities.capability_manager import CapabilityManager
from src.capabilities.capability_registry import CapabilityRegistry
from src.capabilities.resolution import (
    CAPABILITY_GAP,
    DISCOVERING,
    HARDWARE_INCOMPATIBLE,
    resolve_capability_name,
)
from src.control_center.store import ControlCenterStore
from src.providers.execution_history import ProviderExecutionHistory
from src.providers.provider_manager import ProviderManager


def _history(tmp_path, monkeypatch) -> ProviderExecutionHistory:
    monkeypatch.chdir(tmp_path)
    return ProviderExecutionHistory()


def _no_provider_manager() -> ProviderManager:
    class _Empty:
        def get(self, name): return None
    return _Empty()  # type: ignore[return-value]


# D: a missing REQUIRED capability with nothing in flight registers a
# bounded discovery topic (metadata only) and reports DISCOVERING -- never
# a fabricated selection, never a network/search call itself.
def test_missing_capability_registers_discovery_topic(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)
    store = ControlCenterStore(tmp_path / "s.json")
    registry = CapabilityRegistry(store=store)

    result = resolve_capability_name(
        "wan2_2_video_generation", history=history, capability_registry=registry,
        provider_manager=_no_provider_manager(), allow_discovery_topic=True,
    )

    research = store.snapshot()["autonomous_research"]
    assert result.status == DISCOVERING
    assert any("capability:wan2_2_video_generation" in (t.get("tags") or []) for t in research["topics"])
    # No search/evaluation actually ran -- registering a topic is metadata
    # only, and does not itself perform discovery.
    assert research["cycles"] == [] and research["findings"] == []


def test_resolving_the_same_missing_capability_twice_does_not_duplicate_topic(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)
    store = ControlCenterStore(tmp_path / "s.json")
    registry = CapabilityRegistry(store=store)
    kwargs = dict(history=history, capability_registry=registry, provider_manager=_no_provider_manager(),
                  allow_discovery_topic=True)

    resolve_capability_name("wan2_2_video_generation", **kwargs)
    resolve_capability_name("wan2_2_video_generation", **kwargs)

    topics = [t for t in store.snapshot()["autonomous_research"]["topics"]
              if "capability:wan2_2_video_generation" in (t.get("tags") or [])]
    assert len(topics) == 1


# F: Wan2.2 hardware-compatibility fixture (Phase 7) -- open source, CUDA
# classified REQUIRED by the EXISTING evaluator, local GPU unknown -> the
# resolver must report HARDWARE_INCOMPATIBLE, never READY, and must not
# treat "open source" as "available".
def _wan22_candidate(store) -> dict:
    row = {"capability_id": "wan2.2", "category": "text_to_video", "repository": "Wan-Video/Wan2.2",
           "name": "Wan2.2", "status": "VERIFIED_CANDIDATE", "discovery_state": "VERIFIED_CANDIDATE",
           "available": False}
    store.update(lambda s: s["autonomous_research"]["tools"].append(row))
    return row


def test_wan22_style_candidate_is_hardware_incompatible(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)
    store = ControlCenterStore(tmp_path / "s.json")
    _wan22_candidate(store)
    evidence = RepositoryEvidence(
        repository_url="https://github.com/Wan-Video/Wan2.2",
        readme="Wan2.2 is an open source video generation model. CUDA required for local inference. "
               "Install with pip. Usage: python generate.py",
        files={"requirements.txt": "torch\n", "LICENSE": "Apache License Version 2.0"},
        metadata={"license": "Apache-2.0"},
    )
    CapabilityManager(store, evaluator=PassiveCapabilityEvaluator()).evaluate(
        "wan2.2", evidence, {"gpu": "UNKNOWN", "cuda": "UNKNOWN"},
    )
    registry = CapabilityRegistry(store=store)

    result = resolve_capability_name(
        "wan2.2", history=history, capability_registry=registry,
        provider_manager=_no_provider_manager(), allow_discovery_topic=False,
    )

    assert result.status == HARDWARE_INCOMPATIBLE
    assert result.status != "READY"


# K: resolving a capability never installs, sandboxes, or activates
# anything -- the store's proposal/sandbox/integration/capability rows are
# byte-for-byte unchanged by a resolution call.
def test_resolution_never_advances_or_mutates_the_capability_pipeline(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)
    store = ControlCenterStore(tmp_path / "s.json")
    _wan22_candidate(store)
    evidence = RepositoryEvidence(
        repository_url="https://github.com/Wan-Video/Wan2.2",
        readme="Wan2.2 is an open source video generation model. CUDA required for local inference. "
               "Install with pip. Usage: python generate.py",
        files={"requirements.txt": "torch\n", "LICENSE": "Apache License Version 2.0"},
        metadata={"license": "Apache-2.0"},
    )
    CapabilityManager(store, evaluator=PassiveCapabilityEvaluator()).evaluate(
        "wan2.2", evidence, {"gpu": "UNKNOWN", "cuda": "UNKNOWN"},
    )
    registry = CapabilityRegistry(store=store)
    before = copy.deepcopy(store.snapshot())

    resolve_capability_name(
        "wan2.2", history=history, capability_registry=registry, provider_manager=_no_provider_manager(),
        allow_discovery_topic=False,
    )

    after = store.snapshot()
    assert after["autonomous_research"]["proposals"] == before["autonomous_research"]["proposals"]
    assert after["autonomous_research"]["capabilities"] == before["autonomous_research"]["capabilities"] == []
    assert after["autonomous_research"]["tools"] == before["autonomous_research"]["tools"]
