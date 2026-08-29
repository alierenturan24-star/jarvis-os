from __future__ import annotations

from src.capabilities.capability_registry import CapabilityRegistry
from src.capabilities.resolution import CAPABILITY_GAP, READY, CapabilityResolution
from src.control_center.store import ControlCenterStore
from src.core.task_plan import TaskPlan
from src.jobs.job_manager import JobManager
from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus
from src.mission.models import Mission, MissionType
from src.mission.recovery import (
    MissionRecoveryReport,
    _continue_capability_gaps,
    _exact_runtime_gaps,
    plan_needs_recovery,
)


class RecordingCollector:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    def collect(self, focus="", max_results_per_query=3, *, broad=True):
        self.calls.append((focus, broad))
        return list(self.rows)


def media_gap_plan(handler=None):
    task = Task(
        title="media", agent="media", handler=handler or (lambda _task: "artifact produced"),
        metadata={
            "last_stage": "text_to_image_scene_1_via_nvidia/model",
            "capability_gap": {
                "missing_capabilities": ["scene_generation", "narration_generation"],
                "reason": "CAPABILITY_GAP: dynamic provider scene generation failed",
            },
        },
    )
    task.status = TaskStatus.COMPLETED
    task.result = TaskResult(True, "CAPABILITY_GAP: dynamic provider scene generation failed")
    plan = TaskPlan("video")
    plan.add_task(task)
    mission = Mission(title="video", goal="video", mission_type=MissionType.MEDIA,
                      departments=["media"], tasks=[task], capability_gaps=("media_artifact",))
    return mission, plan, task


def test_normal_success_does_not_need_recovery_or_discovery():
    task = Task(title="ok", agent="media", handler=lambda _task: "ok")
    task.status = TaskStatus.COMPLETED
    task.result = TaskResult(True, "real artifact")
    plan = TaskPlan("ok")
    plan.add_task(task)
    assert plan_needs_recovery(plan) is False


def test_runtime_gap_preserves_exact_stage_capability_and_identity():
    mission, plan, task = media_gap_plan()
    gap = _exact_runtime_gaps(mission, plan)[0]
    assert gap["mission_id"] == mission.id
    assert gap["blocked_task_id"] == task.id
    assert gap["requirement"] == "text_to_image"
    assert gap["checkpoint"] == "text_to_image_scene_1_via_nvidia/model"


def test_inventory_ready_retries_original_task_before_discovery(monkeypatch):
    mission, plan, task = media_gap_plan()
    collector = RecordingCollector()
    monkeypatch.setattr(
        "src.mission.recovery.resolve_capability_requirement",
        lambda *args, **kwargs: CapabilityResolution("text_to_image", READY, resolved_by="configured"),
    )
    report = MissionRecoveryReport(goal=mission.goal)
    _continue_capability_gaps(mission, plan, report, evolution_collector=collector,
                              job_manager=JobManager(), capability_registry=CapabilityRegistry())
    assert collector.calls == []
    assert task.status == TaskStatus.COMPLETED
    assert report.used_candidates[0]["capability"] == "text_to_image"


def test_unresolved_gap_enters_canonical_persistent_lifecycle(monkeypatch, tmp_path):
    mission, plan, task = media_gap_plan()
    store = ControlCenterStore(tmp_path / "state.json")
    collector = RecordingCollector([{
        "title": "Example tool", "url": "https://github.com/acme/example",
        "summary": "candidate only",
    }])
    monkeypatch.setattr(
        "src.mission.recovery.resolve_capability_requirement",
        lambda *args, **kwargs: CapabilityResolution("text_to_image", CAPABILITY_GAP),
    )
    report = MissionRecoveryReport(goal=mission.goal)
    _continue_capability_gaps(
        mission, plan, report, evolution_collector=collector, job_manager=JobManager(),
        capability_registry=CapabilityRegistry(store),
    )
    state = store.snapshot()["autonomous_research"]
    candidate = next(row for row in state["tools"] if row["capability_id"] == "github-acme-example")
    continuation = state["mission_continuations"][0]
    assert collector.calls and collector.calls[0][1] is False
    assert candidate["status"] == "VERIFIED_CANDIDATE"
    assert candidate["available"] is False
    assert candidate["provides_capabilities"] == ["text_to_image"]
    assert continuation["mission_id"] == mission.id
    assert continuation["blocked_task_id"] == task.id
    assert continuation["requirement"] == "text_to_image"
    assert continuation["capability_id"] == candidate["capability_id"]
    assert report.evaluated_candidates == []  # no mission-local duplicate lifecycle


def test_continuation_attempt_is_bounded_when_live_checkpoint_is_missing(tmp_path):
    from src.core.ceo import CEO

    store = ControlCenterStore(tmp_path / "state.json")
    registry = CapabilityRegistry(store)
    ceo = CEO()
    ceo.mission_engine.capability_registry = registry
    store.update(lambda state: state["autonomous_research"]["mission_continuations"].append({
        "continuation_id": "c1", "mission_id": "gone", "blocked_task_id": "t1",
        "requirement": "text_to_image", "capability_id": "cap1", "status": "RESUME_READY",
        "resume_attempts": 0,
    }))
    first = ceo.resume_capability_continuations("cap1")
    second = ceo.resume_capability_continuations("cap1")
    assert first[0]["status"] == "RESUME_FAILED"
    assert second == []
    assert store.snapshot()["autonomous_research"]["mission_continuations"][0]["resume_attempts"] == 1


def test_approved_code_integration_uses_existing_delegate_and_reports_unavailable_worker(tmp_path):
    from src.control_center.service import ControlCenterService

    store = ControlCenterStore(tmp_path / "state.json")
    store.update(lambda state: state["autonomous_research"]["integration_plans"].append({
        "integration_plan_id": "plan1", "capability_id": "cap1", "current": True,
    }))
    class Runtime:
        state = "running"
        BOOTING = "booting"

        @staticmethod
        def shutdown():
            pass

    service = ControlCenterService(Runtime(), store)
    approval = service.propose_capability_build("cap1", str(tmp_path), run_tests=True)
    service.decide_approval(approval["id"], True)

    class AdapterRegistry:
        @staticmethod
        def resolve(_department):
            def unavailable(task):
                task.metadata.update(status="FAILED", delegated_to="claude_code", files_changed=[],
                                     tests_executed=False, approval_required=False)
                return "Claude Code CLI kullanılamıyor"
            return unavailable

    outcome = service.execute_capability_build(approval["id"], adapter_registry=AdapterRegistry())
    assert outcome["status"] == "CODING_WORKER_UNAVAILABLE"
    assert store.snapshot()["autonomous_research"]["capabilities"] == []


def test_verified_active_capability_resumes_original_task_and_only_stale_dependents(tmp_path):
    from datetime import datetime, timezone
    from src.core.ceo import CEO

    store = ControlCenterStore(tmp_path / "state.json")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store.update(lambda state: state["autonomous_research"]["capabilities"].append({
        "capability_id": "cap1", "status": "ACTIVE_CAPABILITY", "available": True,
        "requires_approval": False, "verification_valid": True, "last_verified_at": now,
        "provides_capabilities": ["custom_exact"],
    }))
    producer = Task(title="producer", agent="media", handler=lambda _task: "real artifact")
    producer.status = TaskStatus.COMPLETED
    producer.result = TaskResult(True, "CAPABILITY_GAP")
    dependent = Task(title="dependent", agent="learning", handler=lambda _task: "validated")
    dependent.status = TaskStatus.CANCELLED
    unrelated = Task(title="unrelated", agent="research", handler=lambda _task: "must not rerun")
    unrelated.status = TaskStatus.COMPLETED
    unrelated.result = TaskResult(True, "kept")
    plan = TaskPlan("original")
    plan.add_task(producer)
    plan.add_task(dependent, depends_on=(producer,))
    plan.add_task(unrelated)
    mission = Mission(title="original", goal="original", mission_type=MissionType.MEDIA,
                      departments=["media"], tasks=[producer, dependent, unrelated])
    store.update(lambda state: state["autonomous_research"]["mission_continuations"].append({
        "continuation_id": "c1", "mission_id": mission.id, "blocked_task_id": producer.id,
        "requirement": "custom_exact", "capability_id": "cap1", "status": "RESUME_READY",
        "resume_attempts": 0,
    }))
    ceo = CEO()
    ceo.mission_engine.capability_registry = CapabilityRegistry(store)
    ceo._capability_recovery_plans[mission.id] = (mission, plan)
    outcome = ceo.resume_capability_continuations("cap1")[0]
    assert outcome["status"] == "RESUMED"
    assert outcome["resumed_task_id"] == producer.id
    assert outcome["reset_dependent_task_ids"] == [dependent.id]
    assert dependent.status == TaskStatus.COMPLETED
    assert unrelated.result.output == "kept" and unrelated.attempts == 0
