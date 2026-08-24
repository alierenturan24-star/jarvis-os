from __future__ import annotations

import pytest

from src.control_center.service import ControlCenterService
from src.control_center.store import ControlCenterStore
from src.knowledge.knowledge_base import KnowledgeBase
from src.research.collector import ResearchCollector, classify_source
from src.research_loop.autonomous import AutonomousResearchService


class FakeRuntime:
    BOOTING, SLEEPING, STOPPED = "BOOTING", "SLEEPING", "STOPPED"

    def __init__(self):
        self.state = self.BOOTING
        self.completed_tasks = 0
        self.last_error = self.last_mission_status = None
        self.jarvis = type("Jarvis", (), {"last_mission": None})()

    def boot(self):
        self.state = self.SLEEPING

    def shutdown(self):
        self.state = self.STOPPED


def build(tmp_path, monkeypatch, **kwargs):
    monkeypatch.chdir(tmp_path)
    store = ControlCenterStore(tmp_path / "state.json")
    return AutonomousResearchService(store, KnowledgeBase(), **kwargs), store


def github_finding(url="https://github.com/hpcaitech/Open-sora", **extra):
    return {
        "subject": "Open-Sora",
        "predicate": "research_summary",
        "value": "Open-source video generation repository",
        "source_url": url,
        "source_identity": "GitHub",
        "source_type": "GITHUB",
        "verification_state": "VERIFIED_SOURCE",
        "confidence": .9,
        **extra,
    }


@pytest.mark.parametrize("identity", ["Arxiv", "Hacker News"])
def test_bing_aclick_claimed_identity_is_rejected_without_knowledge_write(tmp_path, monkeypatch, identity):
    svc, _ = build(tmp_path, monkeypatch)
    topic = svc.create_topic("video")
    finding = github_finding(
        source_url="https://www.bing.com/aclick?ld=test",
        source_identity=identity,
        source_type="WEB",
    )
    cycle = svc.run_topic(topic["id"], raw_findings=[finding])
    saved = svc.findings(topic["id"])[0]
    assert saved["decision"] == "REJECT"
    assert saved["provenance"]["source_quality_reason"] == "AD_CLICK_URL_REJECTED"
    assert cycle["knowledge_writes"] == 0 and svc.knowledge.facts(topic["id"]) == []


def test_hostname_boundary_and_canonical_github_classification():
    lookalike = classify_source("https://github.com.evil.example/owner/repo")
    canonical = classify_source("https://github.com/hpcaitech/Open-sora")
    assert lookalike["source_type"] == "WEB" and not lookalike["durable_eligible"]
    assert canonical["source_type"] == "GITHUB" and canonical["source_identity"] == "GitHub"
    assert canonical["source_quality_reason"] == "CANONICAL_GITHUB_REPOSITORY"


def test_github_search_channel_does_not_grant_github_identity():
    collector = ResearchCollector()

    class Web:
        def search(self, **kwargs):
            if kwargs["query"].startswith("site:github.com"):
                return {"success": True, "results": [{"title": "ad", "url": "https://example.test/tool", "summary": "x"}]}
            return {"success": False}

    collector.web = Web()
    rows = collector.collect("video")
    assert rows[0]["search_channel"] == "GITHUB"
    assert rows[0]["source_identity"] == "example.test" and rows[0]["source_type"] == "WEB"


def test_source_preferences_are_forwarded_prioritized_and_enforced(tmp_path, monkeypatch):
    calls = []
    collector = ResearchCollector()

    class Web:
        def search(self, **kwargs):
            calls.append(kwargs["query"])
            if kwargs["query"].startswith("site:github.com"):
                return {"success": True, "results": [{"title": "repo", "url": "https://github.com/acme/video", "summary": "tool"}]}
            if kwargs["query"] == "video":
                return {"success": True, "results": [{"title": "web", "url": "https://example.test/video", "summary": "web"}]}
            return {"success": False}

    collector.web = Web()
    rows = collector.collect("video", source_preferences=["OFFICIAL_DOCS", "GITHUB"])
    assert calls[0].endswith("official documentation") and calls[1].startswith("site:github.com")
    assert [row["source_type"] for row in rows] == ["GITHUB"]

    svc, _ = build(tmp_path, monkeypatch, collector=collector)
    topic = svc.create_topic("video", source_preferences=["GITHUB"])
    svc.run_topic(topic["id"])
    assert svc.findings(topic["id"])[0]["provenance"]["source_preference_match"] is True


def test_unverified_generic_web_is_audited_but_not_durable(tmp_path, monkeypatch):
    svc, _ = build(tmp_path, monkeypatch)
    topic = svc.create_topic("video")
    cycle = svc.run_topic(topic["id"], raw_findings=[{
        "subject": "web", "predicate": "claim", "value": "value",
        "source_url": "https://example.test/page", "confidence": .9,
    }])
    finding = svc.findings(topic["id"])[0]
    assert finding["decision"] == "INSUFFICIENT_EVIDENCE"
    assert finding["provenance"]["source_quality_reason"] == "UNVERIFIED_UNTRUSTED_NOT_DURABLE"
    assert cycle["knowledge_writes"] == 0 and svc.knowledge.facts(topic["id"]) == []


def test_same_canonical_fact_second_cycle_is_no_change_without_write(tmp_path, monkeypatch):
    svc, _ = build(tmp_path, monkeypatch)
    topic = svc.create_topic("video")
    first = svc.run_topic(topic["id"], raw_findings=[github_finding()])
    second = svc.run_topic(topic["id"], raw_findings=[github_finding()])
    assert first["new_findings"] == 1 and first["knowledge_writes"] == 1
    assert second["unchanged_findings"] == 1 and second["knowledge_writes"] == 0


def test_live_schema_github_finding_creates_passive_candidate_without_tool_field(tmp_path, monkeypatch):
    svc, store = build(tmp_path, monkeypatch)
    topic = svc.create_topic("Open-source AI video generation tools")
    assert "tool" not in github_finding()
    svc.run_topic(topic["id"], raw_findings=[github_finding()])
    research = store.snapshot()["autonomous_research"]
    candidate = research["tools"][0]
    assert candidate["repository"] == "hpcaitech/Open-sora"
    assert candidate["status"] == "VERIFIED_CANDIDATE" and not candidate["available"]
    assert research["capabilities"] == [] and research["proposals"] == []


@pytest.mark.parametrize("side_effect", [
    {"requires_installation": True},
    {"requires_api_key": True, "configured": False},
    {"requires_oauth": True},
])
def test_sensitive_candidate_uses_existing_pending_proposal_and_never_activates(tmp_path, monkeypatch, side_effect):
    svc, store = build(tmp_path, monkeypatch, probes={"CLI": lambda _: False})
    topic = svc.create_topic("video")
    finding = github_finding(tool={"name": "guarded", "access_method": "CLI", **side_effect})
    svc.run_topic(topic["id"], raw_findings=[finding])
    state = store.snapshot()
    assert state["autonomous_research"]["tools"][0]["status"] == "APPROVAL_REQUIRED"
    assert state["autonomous_research"]["capabilities"] == []
    assert state["autonomous_research"]["proposals"][0]["status"] == "PENDING"
    assert state["approvals"][0]["status"] == "PENDING"


def test_approval_is_record_only_and_stays_pending_executor(tmp_path, monkeypatch):
    calls = []
    svc, store = build(tmp_path, monkeypatch, probes={"CLI": lambda _: calls.append("probe") or False})
    topic = svc.create_topic("video")
    svc.run_topic(topic["id"], raw_findings=[github_finding(tool={
        "name": "installer", "access_method": "CLI", "requires_installation": True,
    })])
    approval = store.snapshot()["approvals"][0]
    before_calls = list(calls)
    ControlCenterService(FakeRuntime(), store).decide_approval(approval["id"], True, "reviewed")
    state = store.snapshot()
    assert calls == before_calls
    assert state["autonomous_research"]["proposals"][0]["status"] == "APPROVED_PENDING_EXECUTOR"
    assert state["autonomous_research"]["tools"][0]["status"] == "APPROVAL_REQUIRED"
    assert state["autonomous_research"]["capabilities"] == []


def test_source_quality_reason_is_in_finding_and_cycle_telemetry(tmp_path, monkeypatch):
    svc, _ = build(tmp_path, monkeypatch)
    topic = svc.create_topic("video")
    cycle = svc.run_topic(topic["id"], raw_findings=[github_finding()])
    finding = svc.findings(topic["id"])[0]
    assert finding["provenance"]["source_quality_reason"] == "CANONICAL_GITHUB_REPOSITORY"
    assert cycle["source_quality_reasons"] == {"CANONICAL_GITHUB_REPOSITORY": 1}


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/private",
    "https://www.google.com/url?q=http://127.0.0.1/private",
])
def test_unsafe_or_unresolved_redirect_is_rejected(tmp_path, monkeypatch, url):
    svc, _ = build(tmp_path, monkeypatch)
    topic = svc.create_topic("video")
    cycle = svc.run_topic(topic["id"], raw_findings=[github_finding(source_url=url, source_identity="")])
    finding = svc.findings(topic["id"])[0]
    assert finding["decision"] == "REJECT"
    assert finding["provenance"]["source_quality_reason"] == "REDIRECT_DESTINATION_UNRESOLVED"
    assert cycle["knowledge_writes"] == 0


def test_knowledge_base_defense_in_depth_rejects_spoofed_accept(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    knowledge = KnowledgeBase()
    finding = {"subject": "x", "predicate": "y", "value": "z", "provenance": {
        "durable_eligible": False, "verification_state": "UNVERIFIED", "source_quality_rejected": False,
    }}
    assert knowledge.persist_fact(finding, "ACCEPT_NEW") is None
    assert knowledge.facts() == []
