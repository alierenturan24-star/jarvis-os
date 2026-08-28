"""Regression tests for the FOURTH real live regression run (same exact
live command as rounds 1-3 -- see ``test_swiss_insider_mission_repair_round3
.py`` for the earlier root causes; this module covers what remained AFTER
those fixes).

Real result: "Jarvis İsviçre için video üret." -> fast routing now correctly
resolves to MEDIA/media+research (rounds 1-3 fixes hold), but:

  PROBLEM A (research quality): the derived research query --
    "{context} güncel YouTube Shorts içerik fırsatı araştır" -- read as a
    CREATOR-GROWTH/TOOLING question ("how do I find Shorts content
    opportunities"), not "what is currently happening in {context} that
    could BECOME a Short". Real evidence: it returned SEO/view-buying/
    tagging advice, AND (``ResearchCollector.collect`` unconditionally also
    runs a ``site:github.com {topic}`` search for every topic) open-source
    "Shorts generator" repositories. See ``_media_research_query`` in
    ``department_orchestrator.py`` for the fixed wording.

  PROBLEM B (quality_check timeout / missing artifact): a media task
    reached ``last_stage="quality_check"`` and was then killed by the
    shared 75s outer department timeout before the quality gate itself
    finished. The final mission report claimed "ARTIFACT STATUS: MISSING"
    even though a real video had already been rendered, because
    ``MediaManager._produce_with_bounded_repair`` used to record
    ``self.last_artifact_path`` only AFTER the (blocking) quality-check
    call returned -- a call that never got the chance to. See
    ``src/media/manager.py`` (artifact recorded BEFORE the quality check
    now, into the same live ``stage_sink`` dict used for ``last_stage``),
    ``src/media/quality.py`` (named quality substages +
    ``quality_check_worst_case_seconds``), and
    ``src/mission/department_orchestrator.py``
    (``MEDIA_DEPARTMENT_TASK_TIMEOUT_SECONDS``, sized from that real inner
    worst-case instead of falling back to the shared 75s default).

Uses mocks/synthetic fixtures only -- no live network/API/paid/YouTube/
finance calls. Does NOT run the real mission and does NOT claim a real
video was produced.
"""

from __future__ import annotations

from src.mission.department_orchestrator import (
    DEPARTMENT_TASK_TIMEOUT_SECONDS,
    MEDIA_DEPARTMENT_TASK_TIMEOUT_SECONDS,
    DepartmentOrchestrator,
    _media_research_query,
)
from src.mission.target_resolver import has_acquisition_signal

LIVE_COMMAND = "Jarvis İsviçre için video üret."


# --- PROBLEM A: research target is current-events, not creator-growth ----------


def test_round4_research_query_asks_about_current_events_not_growth_advice():
    query = _media_research_query(LIVE_COMMAND).casefold()
    # Freshness / current events / trends / public interest -- the requested
    # framing (never hardcoded to Switzerland/a specific story).
    assert any(cue in query for cue in ("gündem", "haber", "gelişme", "trend"))
    assert "güncel" in query or "bugün" in query
    # Never phrased as a creator-growth/tooling question again.
    assert "youtube" not in query
    assert "içerik fırsatı araştır" not in query


def test_round4_research_query_has_no_acquisition_signal():
    # A pure content-opportunity research target must never itself read as
    # a tool/repo/provider ACQUISITION request (shared, generic vocabulary
    # check -- see target_resolver.has_acquisition_signal). This is the
    # SAME signal that already keeps GitHub-category search off content
    # missions (round 3); the query text itself must not accidentally trip
    # it back on for an unrelated reason (e.g. mentioning "tool"/"repo").
    query = _media_research_query(LIVE_COMMAND)
    assert has_acquisition_signal(query) is False


def test_round4_research_query_still_carries_the_market_context():
    query = _media_research_query(LIVE_COMMAND)
    assert "İsviçre" in query
    assert "video üret" not in query.casefold()


def test_round4_github_still_not_dispatched_for_pure_media_production():
    # Content research and capability/tool research remain separate: this
    # mission must never silently pick up a GitHub/tool search.
    departments = DepartmentOrchestrator().select_departments(LIVE_COMMAND)
    assert "github" not in departments
    assert set(departments) == {"research", "media"}


# --- PROBLEM B: artifact preservation across a quality_check failure/timeout ---


def test_round4_artifact_path_is_recorded_before_the_quality_check_call(tmp_path, monkeypatch):
    """The real bug: ``self.last_artifact_path``/``stage_sink["artifact_path"]``
    used to be written only AFTER ``validate_media_goal_artifact`` returned.
    If that call never returns (killed by the outer department timeout),
    the real rendered file was reported as if it never existed. Proven here
    by making the quality check raise instead of return -- the artifact
    path must already be recorded on both signals before that happens."""
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
        # Stand-in for "killed by the outer department timeout before
        # returning" -- whatever happens to this call, the artifact must
        # already be recorded by the time it's reached.
        raise TimeoutError("simulated: quality_check exceeded the department budget")

    monkeypatch.setattr("src.media.manager.validate_media_goal_artifact", _quality_check_never_returns)

    raised = False
    try:
        manager._produce_with_bounded_repair(
            LIVE_COMMAND, "plan text", 60, lambda: None, stage_sink=stage_sink,
        )
    except TimeoutError:
        raised = True

    assert raised, "expected the simulated quality_check failure to propagate"
    assert manager.last_artifact_path == str(artifact)
    assert stage_sink.get("artifact_path") == str(artifact)
    assert stage_sink.get("last_stage") == "quality_check_start"


def _media_mission_with_real_but_unapproved_artifact(tmp_path):
    from src.jobs.task import Task
    from src.jobs.task_result import TaskResult
    from src.jobs.task_status import TaskStatus
    from src.mission.completion import infer_completion_requirements
    from src.mission.models import Mission, MissionType

    video = tmp_path / "video.mp4"
    # Real, non-empty, correctly-extensioned file -- but not a valid MP4
    # container, so technical quality validation genuinely fails. Stands in
    # for "render succeeded, quality_check genuinely rejected it" (or timed
    # out after registering the path -- either way the file is real).
    video.write_bytes(b"x" * 2048)

    task = Task(title="[media] x", agent="media", handler=lambda t: "ok",
                metadata={"artifact_path": str(video)})
    task.status = TaskStatus.COMPLETED
    task.result = TaskResult(success=True, output="ok")

    mission = Mission(
        title=LIVE_COMMAND, goal=LIVE_COMMAND, mission_type=MissionType.MEDIA,
        departments=["media"], tasks=[task],
    )
    mission.completion_requirements = infer_completion_requirements(mission.title, mission.departments)
    return mission


def test_round4_qc_failure_does_not_mark_mission_completed(tmp_path):
    from src.mission.completion import evaluate_goal_completion

    mission = _media_mission_with_real_but_unapproved_artifact(tmp_path)
    completion = evaluate_goal_completion(mission)
    assert completion.satisfied is False


def test_round4_qc_failure_with_real_artifact_is_not_reported_as_missing(tmp_path):
    from src.mission.completion import evaluate_goal_completion

    mission = _media_mission_with_real_but_unapproved_artifact(tmp_path)
    completion = evaluate_goal_completion(mission)
    video_status = next(item for item in completion.requirements if item.requirement.name == "video")
    assert video_status.satisfied is False  # still not complete/approved
    assert video_status.rendered_not_approved is True  # but truthfully NOT "missing" either


def test_round4_self_check_shows_rendered_not_approved_not_missing(tmp_path):
    from src.strategy.execution_planner import build_self_check

    mission = _media_mission_with_real_but_unapproved_artifact(tmp_path)
    check = build_self_check(mission, None)
    assert "RENDERED_NOT_APPROVED" in check.artifact_statuses
    assert "MISSING" not in check.artifact_statuses


def test_round4_no_artifact_at_all_still_reports_missing():
    # The new distinction must not blur the genuinely-empty case -- no
    # artifact_path anywhere in task metadata still reads as plain MISSING.
    from src.jobs.task import Task
    from src.jobs.task_result import TaskResult
    from src.jobs.task_status import TaskStatus
    from src.mission.completion import infer_completion_requirements
    from src.mission.models import Mission, MissionType
    from src.strategy.execution_planner import build_self_check

    task = Task(title="[media] x", agent="media", handler=lambda t: "ok")
    task.status = TaskStatus.COMPLETED
    task.result = TaskResult(success=True, output="plan hazır")
    mission = Mission(title="Video üret.", goal="Video üret.", mission_type=MissionType.MEDIA,
                       departments=["media"], tasks=[task])
    mission.completion_requirements = infer_completion_requirements(mission.title, mission.departments)

    check = build_self_check(mission, None)
    assert check.artifact_statuses == ("MISSING",)


# --- Quality substage evidence (last_stage before every blocking call) ---------


def test_round4_quality_check_marks_technical_validation_before_first_probe(tmp_path, monkeypatch):
    import subprocess

    from src.media.quality import validate_media_goal_artifact

    monkeypatch.setattr("src.media.renderer.find_ffprobe", lambda: "ffprobe.exe")

    def _boom(*args, **kwargs):
        raise AssertionError("no subprocess should actually run in this test")

    monkeypatch.setattr(subprocess, "run", _boom)

    video = tmp_path / "artifact.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftyp" + b"x" * 2000)  # passes the fast pre-subprocess checks

    sink: dict = {}
    try:
        validate_media_goal_artifact(video, "goal", stage_sink=sink)
    except AssertionError:
        pass

    assert sink.get("last_stage") == "quality_technical_validation"


# NOTE: the per-scene body-motion substage marker test lives in
# src/media/tests/test_quality_gates.py instead of here -- this module's
# directory (src/mission/tests/) has an autouse fixture
# (deterministic_provider_registry, see conftest.py) that replaces
# ``src.media.quality._measure_local_body_motion`` with a no-op double for
# EVERY mission test, which would make a direct test of that function's
# real body a false negative here.


# --- Time-budget structure ------------------------------------------------------


def test_round4_media_department_budget_is_sized_from_real_inner_worst_case():
    from src.media.manager import MAX_REPAIR_ATTEMPTS
    from src.media.quality import quality_check_worst_case_seconds

    # Still finite and still bounded -- no infinite waits, no unlimited
    # retries (MAX_REPAIR_ATTEMPTS is unchanged, just made a public name).
    assert MAX_REPAIR_ATTEMPTS == 2

    expected = (
        DEPARTMENT_TASK_TIMEOUT_SECONDS
        + (1 + MAX_REPAIR_ATTEMPTS) * quality_check_worst_case_seconds()
        + 15.0
    )
    assert MEDIA_DEPARTMENT_TASK_TIMEOUT_SECONDS == expected
    # The whole point of the round 4 fix: media's outer budget must now
    # exceed the shared base default it silently fell back to before.
    assert MEDIA_DEPARTMENT_TASK_TIMEOUT_SECONDS > DEPARTMENT_TASK_TIMEOUT_SECONDS


def test_round4_media_department_timeout_is_actually_wired_up():
    from src.mission.department_orchestrator import _DEPARTMENT_TASK_TIMEOUTS

    assert _DEPARTMENT_TASK_TIMEOUTS.get("media") == MEDIA_DEPARTMENT_TASK_TIMEOUT_SECONDS


# --- YouTube publish remains approval-gated (unchanged; reconfirmed) -----------


def test_round4_publish_actions_remain_medium_or_higher_risk():
    from src.security.action_policy import ActionPolicy

    assert "publish_scheduled_video" not in ActionPolicy.LOW_RISK_ACTIONS
    assert "upload_private_video" not in ActionPolicy.LOW_RISK_ACTIONS
