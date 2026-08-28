from __future__ import annotations

import pytest

import src.mission.mission_engine as mission_module
from src.capabilities.capability_registry import CapabilityRegistry
from src.control_center.service import ControlCenterService
from src.control_center.store import ControlCenterStore
from src.knowledge.knowledge_base import KnowledgeBase
from src.mission.mission_engine import MissionEngine
from src.research_loop.autonomous import AutonomousResearchService
from src.research.collector import ResearchCollector
import src.research.collector as collector_module


class NoStrategy:
    def plan(self, _request): return None


class FakeRuntime:
    BOOTING, SLEEPING, STOPPED = "BOOTING", "SLEEPING", "STOPPED"
    def __init__(self):
        self.state = self.BOOTING; self.completed_tasks = 0; self.last_error = self.last_mission_status = None
        self.jarvis = type("Jarvis", (), {"last_mission": None})()
    def boot(self): self.state = self.SLEEPING
    def shutdown(self): self.state = self.STOPPED


def evidence(tool):
    return {"subject": tool["name"], "predicate": "capability", "value": "verified capability",
            "source_url": "https://example.test/docs", "source_identity": "official docs",
            "source_type": "OFFICIAL_DOCS", "verification_state": "VERIFIED_ADAPTER",
            "confidence": .9, "tool": tool}


def build(tmp_path, monkeypatch, **kwargs):
    monkeypatch.chdir(tmp_path)
    store = ControlCenterStore(tmp_path / "state.json")
    return AutonomousResearchService(store, KnowledgeBase(), **kwargs), store


def test_safe_active_capability_is_mission_availability_signal_only(tmp_path, monkeypatch):
    svc, store = build(tmp_path, monkeypatch, probes={"CLI": lambda _: True})
    topic = svc.create_topic("video")
    svc.run_topic(topic["id"], raw_findings=[evidence({"name": "beta", "category": "VIDEO_GENERATION",
        "provides_capabilities": ["media_artifact"], "access_method": "CLI", "safe_probe": True})])
    candidate = store.snapshot()["autonomous_research"]["tools"][0]
    store.update(lambda state: state["autonomous_research"]["capabilities"].append(
        {**candidate, "status": "ACTIVE_CAPABILITY", "requires_approval": False, "verification_valid": True}))
    registry = CapabilityRegistry(store)
    before = dict(store.snapshot()["autonomous_research"]["capabilities"][0])
    monkeypatch.setattr(mission_module, "has_production_media_capability", lambda _: False)
    mission = MissionEngine(strategy_engine=NoStrategy(), capability_registry=registry).create_mission("YouTube için video üret")
    assert "media_artifact" in mission.current_capabilities
    assert mission.capability_candidates[0]["capability_id"] == "beta"
    after = store.snapshot()["autonomous_research"]["capabilities"][0]
    assert (after["success_count"], after["failure_count"], after["last_used_at"]) == (
        before["success_count"], before["failure_count"], before["last_used_at"])


def test_unavailable_and_approval_required_capabilities_are_not_selected(tmp_path, monkeypatch):
    svc, store = build(tmp_path, monkeypatch, probes={"CLI": lambda _: False})
    topic = svc.create_topic("tools")
    svc.run_topic(topic["id"], raw_findings=[evidence({"name": "missing", "category": "analysis",
        "access_method": "CLI"}), evidence({"name": "installable", "category": "analysis",
        "access_method": "CLI", "requires_installation": True})])
    assert CapabilityRegistry(store).select("analysis") == []


def test_proposal_uses_existing_exact_bound_approval_and_never_executes(tmp_path, monkeypatch):
    svc, store = build(tmp_path, monkeypatch, probes={"CLI": lambda _: False})
    topic = svc.create_topic("tools")
    svc.run_topic(topic["id"], raw_findings=[evidence({"name": "installer", "access_method": "CLI",
        "requires_installation": True, "description": "Install local tool"})])
    state = store.snapshot(); proposal = state["autonomous_research"]["proposals"][0]
    approval = state["approvals"][0]
    assert approval["binding"] == {"proposal_id": proposal["proposal_id"], "capability_id": proposal["capability_id"],
                                    "requested_action": "INSTALL"}
    service = ControlCenterService(FakeRuntime(), store)
    decided = service.decide_approval(approval["id"], True, "reviewed")
    assert decided["status"] == "APPROVED"
    assert store.snapshot()["autonomous_research"]["proposals"][0]["status"] == "APPROVED_PENDING_EXECUTOR"
    assert store.snapshot()["autonomous_research"]["tools"][0]["status"] == "APPROVAL_REQUIRED"
    with pytest.raises(KeyError): service.decide_approval(approval["id"], True)


def test_proposal_binding_cannot_be_replayed_for_another_proposal(tmp_path, monkeypatch):
    svc, store = build(tmp_path, monkeypatch, probes={"CLI": lambda _: False})
    topic = svc.create_topic("tools")
    svc.run_topic(topic["id"], raw_findings=[evidence({"name": "a", "access_method": "CLI", "requires_oauth": True}),
                                             evidence({"name": "b", "access_method": "CLI", "requires_payment": True})])
    state = store.snapshot(); approval = state["approvals"][0]; other = state["autonomous_research"]["proposals"][1]
    store.update(lambda s: next(x for x in s["approvals"] if x["id"] == approval["id"])["binding"].update(
        proposal_id=other["proposal_id"], capability_id=other["capability_id"]))
    with pytest.raises(RuntimeError, match="BINDING_MISMATCH"):
        ControlCenterService(FakeRuntime(), store).decide_approval(approval["id"], True)


def test_rejected_oauth_or_payment_never_becomes_candidate(tmp_path, monkeypatch):
    svc, store = build(tmp_path, monkeypatch, probes={"CLI": lambda _: False})
    topic = svc.create_topic("tools")
    svc.run_topic(topic["id"], raw_findings=[evidence({"name": "oauth-tool", "category": "analysis",
        "access_method": "CLI", "requires_oauth": True})])
    approval = store.snapshot()["approvals"][0]
    ControlCenterService(FakeRuntime(), store).decide_approval(approval["id"], False)
    assert CapabilityRegistry(store).select("analysis") == []


@pytest.mark.parametrize("flag,action", [("publication", "PUBLICATION"), ("finance_live", "FINANCE_LIVE"),
                                           ("requires_payment", "PAYMENT"), ("requires_oauth", "OAUTH")])
def test_sensitive_capability_cannot_bypass_policy_registry(tmp_path, monkeypatch, flag, action):
    svc, store = build(tmp_path, monkeypatch, probes={"CLI": lambda _: True})
    topic = svc.create_topic("guard")
    svc.run_topic(topic["id"], raw_findings=[evidence({"name": "guarded", "category": "analysis",
        "access_method": "CLI", flag: True})])
    state = store.snapshot()
    assert state["autonomous_research"]["proposals"][0]["requested_action"] == action
    assert CapabilityRegistry(store).select("analysis") == []


def test_usage_telemetry_changes_only_on_real_invocation(tmp_path, monkeypatch):
    svc, store = build(tmp_path, monkeypatch, probes={"CLI": lambda _: True})
    topic = svc.create_topic("tools")
    svc.run_topic(topic["id"], raw_findings=[evidence({"name": "reader", "category": "analysis",
        "access_method": "CLI", "safe_probe": True})])
    candidate = store.snapshot()["autonomous_research"]["tools"][0]
    store.update(lambda state: state["autonomous_research"]["capabilities"].append(
        {**candidate, "status": "ACTIVE_CAPABILITY", "requires_approval": False, "verification_valid": True}))
    registry = CapabilityRegistry(store)
    assert registry.select("analysis")
    assert registry.invoke("reader", lambda: "ok") == "ok"
    with pytest.raises(ValueError): registry.invoke("reader", lambda: (_ for _ in ()).throw(ValueError("failed")))
    row = store.snapshot()["autonomous_research"]["capabilities"][0]
    assert row["success_count"] == 1 and row["failure_count"] == 1 and row["last_used_at"]


def test_hard_timeout_discards_staged_facts_clears_lock_and_backs_off(tmp_path, monkeypatch):
    ticks = iter([0.0, 0.1, 0.2, 2.0])
    svc, _ = build(tmp_path, monkeypatch, monotonic=lambda: next(ticks))
    topic = svc.create_topic("timeout")
    cycle = svc.run_topic(topic["id"], raw_findings=[evidence({"name": "late", "access_method": "CLI"})], max_runtime=1)
    saved = svc.topics()[0]
    assert cycle["status"] == "TIMEOUT" and cycle["knowledge_writes"] == 0
    assert svc.knowledge.facts(topic["id"]) == [] and svc.findings(topic["id"]) == []
    assert saved["running_cycle_id"] is None and saved["consecutive_failures"] == 1
    assert saved["next_research_at"] > saved["last_researched_at"]


def test_existing_collector_propagates_remaining_deadline_to_network_adapter(monkeypatch):
    observed = []
    collector = ResearchCollector()
    collector.web = type("Web", (), {"search": lambda self, **kwargs: observed.append(kwargs["timeout_seconds"])
                                      or {"success": False}})()
    ticks = iter([10.0, 12.0])
    monkeypatch.setattr(collector_module.time, "monotonic", lambda: next(ticks))
    # Round 5: GITHUB/HACKER_NEWS are no longer unconditional channels (see
    # collector._wants_tooling_sources) -- this test needs >= 2 search
    # steps to exercise the SECOND deadline check, so the topic carries a
    # genuine tooling signal ("tool") to keep multiple channels active;
    # the deadline-propagation behavior under test is unaffected.
    with pytest.raises(TimeoutError): collector.collect("topic tool", deadline=11.0)
    assert observed == [1.0]
