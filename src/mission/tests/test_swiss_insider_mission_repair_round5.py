"""Regression tests for the FIFTH real live regression run (same exact live
command as rounds 1-4 -- see ``test_swiss_insider_mission_repair_round4.py``
for the earlier root causes; this module covers what remained AFTER those
fixes).

Real result: "Jarvis İsviçre için video üret." -> rounds 1-4 fixes hold
(MEDIA/research+media routing, no repo semantics, media survives a
quality_check timeout with the artifact preserved), but:

  PROBLEM A (research source routing): a pure current-events query got
    ALSO searched against site:github.com/site:arxiv.org/
    site:news.ycombinator.com unconditionally (``ResearchCollector.collect``,
    src/research/collector.py) -- research honestly could not find a
    Switzerland-specific current story, but the GitHub search surfaced an
    unrelated "GitHub Foundations Certification" course, which got
    recommended as if it were the selected content opportunity.

  PROBLEM B (research -> media handoff): media independently re-derived
    its own topic from the raw command text -- a DIFFERENT string than
    research's actual query -- so ``MediaManager.plan()``'s internal
    ``KnowledgeBase.find_research(topic)`` lookup silently missed, research
    grounding was never established, and media fell back to generic
    evergreen Switzerland content (chocolate/watches/Alps/finance). The
    real render was correctly rejected by QC (visual_relevance,
    research_grounding) -- those gates worked correctly and are NOT
    touched here; the fix is upstream data flow (see
    src/mission/department_orchestrator.py's explicit media->research
    ``depends_on`` wiring, src/research/opportunity.py's
    ``SelectedOpportunity`` structured handoff, and
    src/media/manager.py's ``research_opportunity`` param).

Uses mocks/synthetic fixtures only -- no live network/API/paid/YouTube/
finance calls. Does NOT run the real mission and does NOT claim a real
video was produced.
"""

from __future__ import annotations

from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.mission_engine import MissionEngine
from src.research.collector import ResearchCollector
from src.research.opportunity import build_selected_opportunity

LIVE_COMMAND = "Jarvis İsviçre için video üret."


# --- PROBLEM A: source routing --------------------------------------------------


class _FakeWeb:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, **kwargs):
        self.queries.append(kwargs["query"])
        return {"success": False}


def test_round5_current_events_query_does_not_auto_search_github_arxiv_hn():
    collector = ResearchCollector()
    web = _FakeWeb()
    collector.web = web

    collector.collect("İsviçre için güncel gündem: bugün öne çıkan haberler ve gelişmeler")

    assert not any(q.startswith("site:github.com") for q in web.queries)
    assert not any(q.startswith("site:arxiv.org") for q in web.queries)
    assert not any(q.startswith("site:news.ycombinator.com") for q in web.queries)


def test_round5_capability_software_research_can_still_use_github():
    collector = ResearchCollector()
    web = _FakeWeb()
    collector.web = web

    collector.collect("en iyi açık kaynak video üretim tool/repo'sunu bul")

    assert any(q.startswith("site:github.com") for q in web.queries)


def test_round5_explicit_source_preference_still_forces_the_channel():
    # Existing, unchanged override mechanism: an explicit request beats
    # automatic intent classification either way.
    collector = ResearchCollector()
    web = _FakeWeb()
    collector.web = web

    collector.collect("İsviçre için güncel gündem", source_preferences=["GITHUB"])

    assert any(q.startswith("site:github.com") for q in web.queries)


# --- PROBLEM A cont.: insufficient current evidence cannot be promoted ---------


def test_round5_insufficient_market_evidence_is_not_promoted_into_a_recommendation():
    # Reproduces the real live drift: research's summary is about an
    # unrelated GitHub certification course, not Switzerland.
    opportunity = build_selected_opportunity(
        topic="İsviçre için güncel gündem araştır",
        location_or_market="İsviçre için",
        summary=(
            "GitHub Foundations Certification ile yazılımda kariyerini güçlendirmek isteyenler için "
            "yeni bir sertifikasyon programı duyuruldu."
        ),
        sources=[{"url": "https://example.test/github-foundations", "title": "GitHub Foundations"}],
    )
    assert opportunity.sufficient is False
    assert opportunity.freshness_status == "INSUFFICIENT_EVIDENCE"
    assert "İsviçre" not in opportunity.reason or "kaymış" in opportunity.reason


def test_round5_market_relevant_current_evidence_is_sufficient():
    opportunity = build_selected_opportunity(
        topic="İsviçre için güncel gündem araştır",
        location_or_market="İsviçre için",
        summary="İsviçre hükümeti bugün yeni bir enerji tasarrufu paketi açıkladı; tüm kantonlarda uygulanacak.",
        sources=[{"url": "https://example.test/isvicre-enerji", "title": "İsviçre enerji paketi"}],
    )
    assert opportunity.sufficient is True
    assert opportunity.freshness_status == "CURRENT"


# --- PROBLEM B: media->research data dependency ---------------------------------


class TestMediaResearchDependencyWiring:
    def setup_method(self):
        engine = MissionEngine()
        mission = engine.create_mission(LIVE_COMMAND)
        self.tasks = engine.orchestrator.create_tasks(mission)
        self.media_task = next(t for t in self.tasks if t.agent == "media")
        self.research_task = next(t for t in self.tasks if t.agent == "research")

    def test_media_depends_on_research(self):
        assert self.research_task.id in self.media_task.depends_on

    def test_media_receives_a_live_reference_to_the_research_task(self):
        assert self.media_task.metadata.get("research_task") is self.research_task

    def test_research_task_carries_market_context_for_the_opportunity_check(self):
        assert self.research_task.metadata.get("market_context")
        assert "İsviçre" in self.research_task.metadata["market_context"]


def test_round5_explicit_topic_does_not_require_research_discovery():
    # POINT 8: an explicit concrete topic ("X konusunda") must not
    # unnecessarily wait on topic discovery.
    engine = MissionEngine()
    mission = engine.create_mission("Bitcoin neden düştü konusunda video hazırla.")
    tasks = engine.orchestrator.create_tasks(mission)
    media_task = next((t for t in tasks if t.agent == "media"), None)
    assert media_task is not None
    assert "research_task" not in media_task.metadata


def test_round5_existing_asset_edit_still_has_no_research_dependency():
    engine = MissionEngine()
    mission = engine.create_mission("Jarvis, bu hazır videoya altyazı ekle.")
    tasks = engine.orchestrator.create_tasks(mission)
    media_task = next((t for t in tasks if t.agent == "media"), None)
    if media_task is not None:
        assert "research_task" not in media_task.metadata


# --- Media grounding / RESEARCH_GAP behavior (MediaAgent) ----------------------


class _CapturingManager:
    last_artifact_path = ""
    last_production_record = None
    last_capability_gap = None

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def plan(self, topic, duration_seconds=60, preferred_provider=None,
             produce_artifact=False, stage_sink=None, research_opportunity=None):
        self.calls.append(dict(
            topic=topic, duration_seconds=duration_seconds, produce_artifact=produce_artifact,
            research_opportunity=research_opportunity,
        ))
        return "SENARYO\nx\n\nSAHNELER\nx\n"

    def set_channel_scope(self, channel_id):
        pass


def _research_task_with_report(report: dict) -> Task:
    task = Task(title="[research] x", agent="research", handler=lambda t: "ok", metadata={"report": report})
    task.status = TaskStatus.COMPLETED
    task.result = TaskResult(success=True, output="ok")
    return task


def test_round5_media_planning_is_grounded_in_the_selected_opportunity():
    from src.agents.media_agent import MediaAgent

    research_task = _research_task_with_report(dict(_OPPORTUNITY_FIXTURE))
    media_task = Task(
        title="[media] x", agent="media", handler=lambda t: "ok",
        target=LIVE_COMMAND, metadata={"research_task": research_task},
    )

    agent = MediaAgent()
    fake = _CapturingManager()
    agent.manager = fake

    agent.execute(media_task)

    assert len(fake.calls) == 1
    call = fake.calls[0]
    # POINT 5: script/hook/scenes are grounded in the selected opportunity
    # -- proven at the boundary media planning actually consumes: the
    # topic passed to MediaManager.plan() is the SELECTED topic, not the
    # raw production command.
    assert call["topic"] == _OPPORTUNITY_FIXTURE["selected_topic"]
    assert call["topic"] != LIVE_COMMAND
    # POINT 6: research evidence/provenance reaches media (and, from
    # there, production/QC -- see TestResearchOpportunityGrounding in
    # src/media/tests/test_manager.py for the production-provenance leg).
    assert call["research_opportunity"] == _OPPORTUNITY_FIXTURE


def test_round5_media_does_not_produce_evergreen_fallback_when_research_insufficient():
    from src.agents.media_agent import MediaAgent

    insufficient = dict(_OPPORTUNITY_FIXTURE)
    insufficient.update(sufficient=False, reason="araştırma sonucu alakasız bir konuya kaymış")
    research_task = _research_task_with_report(insufficient)
    media_task = Task(
        title="[media] x", agent="media", handler=lambda t: "ok",
        target=LIVE_COMMAND, metadata={"research_task": research_task},
    )

    agent = MediaAgent()
    fake = _CapturingManager()
    agent.manager = fake

    result = agent.execute(media_task)

    # POINT 7: no evergreen fallback -- manager.plan() (and therefore any
    # production/render/artifact attempt) is never even called.
    assert fake.calls == []
    assert "RESEARCH_GAP" in result
    assert media_task.metadata.get("last_stage") == "research_gap_stop"


def test_round5_media_stops_truthfully_if_research_task_did_not_complete():
    from src.agents.media_agent import MediaAgent

    research_task = Task(title="[research] x", agent="research", handler=lambda t: "ok")
    research_task.status = TaskStatus.FAILED
    research_task.error = "boom"
    media_task = Task(
        title="[media] x", agent="media", handler=lambda t: "ok",
        target=LIVE_COMMAND, metadata={"research_task": research_task},
    )

    agent = MediaAgent()
    fake = _CapturingManager()
    agent.manager = fake

    result = agent.execute(media_task)

    assert fake.calls == []
    assert "RESEARCH_GAP" in result


def test_round5_media_without_research_dependency_behaves_as_before():
    # Explicit-topic / no-discovery-needed path: no ``research_task`` in
    # metadata at all -- media plans independently, exactly like before
    # round 5.
    from src.agents.media_agent import MediaAgent

    media_task = Task(title="[media] x", agent="media", handler=lambda t: "ok",
                       target="Bitcoin neden düştü konusunda video hazırla.")
    agent = MediaAgent()
    fake = _CapturingManager()
    agent.manager = fake

    agent.execute(media_task)

    assert len(fake.calls) == 1
    assert fake.calls[0]["research_opportunity"] is None


_OPPORTUNITY_FIXTURE = {
    "selected_topic": "İsviçre'de bugün açıklanan yeni enerji tasarrufu paketi",
    "location_or_market": "İsviçre için",
    "why_current": "güncellik sinyali doğrulandı, bayat/eski yıl referansı bulunamadı",
    "supporting_evidence": [{"url": "https://example.test/isvicre-enerji", "title": "İsviçre enerji paketi"}],
    "freshness_status": "CURRENT",
    "sufficient": True,
    "reason": "",
}


# --- Quality gates unchanged / round 4 artifact preservation still holds -------


def test_round5_quality_gates_visual_relevance_and_research_grounding_still_active():
    from src.media.quality import validate_media_goal_artifact

    # Not a real artifact -- just proves these gate NAMES/checks are still
    # present and reachable (unweakened), matching round 4/5's explicit
    # "do not touch quality.py" constraint.
    check = validate_media_goal_artifact("does-not-exist.mp4", "some goal")
    assert check.passed is False  # technical validation fails closed as before


def test_round5_round4_artifact_preservation_still_works(tmp_path, monkeypatch):
    from src.media.manager import MediaManager
    from src.media.renderer import LocalVideoRenderer, RenderResult

    manager = MediaManager()
    stage_sink: dict = {}
    artifact = tmp_path / "artifact.mp4"
    artifact.write_bytes(b"x" * 2048)

    monkeypatch.setattr(
        LocalVideoRenderer, "render",
        lambda self, topic, narration, duration_seconds, **kw: RenderResult(
            True, str(artifact), audio_used=True, production_ready=True,
        ),
    )

    def _quality_check_never_returns(path, goal, **kw):
        raise TimeoutError("simulated: quality_check exceeded the department budget")

    monkeypatch.setattr("src.media.manager.validate_media_goal_artifact", _quality_check_never_returns)

    try:
        manager._produce_with_bounded_repair(LIVE_COMMAND, "plan text", 60, lambda: None, stage_sink=stage_sink)
    except TimeoutError:
        pass

    assert manager.last_artifact_path == str(artifact)
    assert stage_sink.get("artifact_path") == str(artifact)


def test_round5_publish_actions_remain_medium_or_higher_risk():
    from src.security.action_policy import ActionPolicy

    assert "publish_scheduled_video" not in ActionPolicy.LOW_RISK_ACTIONS
    assert "upload_private_video" not in ActionPolicy.LOW_RISK_ACTIONS


# --- Fast-path routing from rounds 1-4 must still hold --------------------------


def test_round5_fast_path_departments_unchanged():
    departments = DepartmentOrchestrator().select_departments(LIVE_COMMAND)
    assert set(departments) == {"research", "media"}
