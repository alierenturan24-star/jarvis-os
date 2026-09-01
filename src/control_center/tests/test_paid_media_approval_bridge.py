from types import SimpleNamespace

from src.agents.media_agent import MediaAgent
from src.control_center.service import ControlCenterService
from src.control_center.store import ControlCenterStore
from src.core.ceo import CEO
from src.core.task_plan import TaskPlan
from src.jobs.task import Task
from src.jobs.task_status import TaskStatus
from src.mission.models import Mission, MissionStatus, MissionType
from src.mission.recovery import MissionRecoveryReport


class _CEO:
    def __init__(self):
        self.calls = []

    def resume_paid_media_approval(self, mission_id, task_id):
        self.calls.append((mission_id, task_id))
        return {"status": "RESUMED", "mission_id": mission_id, "task_id": task_id}


class _Runtime:
    STOPPED = "STOPPED"
    BOOTING = "BOOTING"

    def __init__(self, mission):
        self.state = "RUNNING"
        self.last_error = self.last_error_context = None
        self.last_mission_status = None
        self.completed_tasks = 0
        self.jarvis = SimpleNamespace(last_mission=mission, last_provider_route=None, ceo=_CEO())

    def execute(self, goal, execution_hints=None):
        return "blocked report"


def _blocked_mission():
    task = Task(title="media", agent="media", handler=lambda task: "blocked")
    task.status = TaskStatus.FAILED
    task.metadata.update(approval_action="paid_media_generation",
                         approval_provider_candidates=["nvidia/model", "fal/model", "aiml/model"])
    mission = Mission(title="Short üret", mission_type=MissionType.YOUTUBE,
                      departments=["media"], tasks=[task])
    mission.status = MissionStatus.BLOCKED
    mission.recovery = MissionRecoveryReport(goal=mission.title, ran=True, blocked=True,
        approval_required=[{"task_id": task.id, "department": "media", "need": "Paid media",
                            "why": "APPROVAL_REQUIRED", "why_free_insufficient": "paid only"}])
    return mission, task


def test_blocked_media_creates_one_visible_bound_approval_and_deduplicates(tmp_path):
    mission, task = _blocked_mission()
    service = ControlCenterService(_Runtime(mission), ControlCenterStore(tmp_path / "state.json"))
    record = {"id": "control-record", "goal": mission.title, "source": "text"}

    service._run_command(record)
    service._run_command(record)

    approvals = service.store.snapshot()["approvals"]
    assert len(approvals) == 1
    approval = approvals[0]
    assert approval["status"] == "PENDING"
    assert approval["mission_id"] == mission.id
    assert approval["task_id"] == task.id
    assert approval["action"] == "paid_media_generation"
    assert approval["provider_candidates"] == ["nvidia/model", "fal/model", "aiml/model"]
    assert service.snapshot()["approvals"][0]["id"] == approval["id"]
    assert service.read_model.approvals()[0]["id"] == approval["id"]


def test_approve_resumes_exact_binding_but_other_decisions_do_not(tmp_path):
    mission, task = _blocked_mission()
    runtime = _Runtime(mission)
    service = ControlCenterService(runtime, ControlCenterStore(tmp_path / "state.json"))

    def approval(mid, tid, action="paid_media_generation"):
        return service.create_approval("mission_capability", {
            "task_id": tid, "action": action, "need": "Paid media", "why": "blocked"
        }, mission_id=mid)

    approved = approval(mission.id, task.id)
    service.decide_approval(approved["id"], True, "approved")
    assert runtime.jarvis.ceo.calls == [(mission.id, task.id)]

    rejected = approval("other-mission", "other-task")
    service.decide_approval(rejected["id"], False, "reject")
    changes = approval("third-mission", "third-task")
    service.decide_approval(changes["id"], None, "change")
    unrelated = approval("fourth-mission", "fourth-task", "other_action")
    service.decide_approval(unrelated["id"], True, "approved")
    assert runtime.jarvis.ceo.calls == [(mission.id, task.id)]


def test_media_agent_threads_only_exact_paid_media_permission(monkeypatch):
    seen = []

    class Manager:
        last_artifact_path = ""
        last_production_record = None
        last_capability_gap = None

        def plan(self, topic, duration_seconds=60, preferred_provider=None, produce_artifact=False,
                 stage_sink=None, research_opportunity=None, standing_permission=False):
            seen.append(standing_permission)
            return "blocked"

    agent = MediaAgent()
    agent.manager = Manager()
    first = Task(title="video üret", agent="media", handler=lambda task: None,
                 metadata={"paid_media_permission": "paid_media_generation"})
    second = Task(title="video üret", agent="media", handler=lambda task: None,
                  metadata={"paid_media_permission": "other_action"})
    agent.execute(first)
    agent.execute(second)
    assert seen == [True, False]


def test_ceo_resume_uses_same_mission_and_task_checkpoint(monkeypatch):
    seen = []
    task = Task(title="media", agent="media",
                handler=lambda current: seen.append(current.metadata.get("paid_media_permission")) or "ok")
    task.status = TaskStatus.FAILED
    mission = Mission(title="same mission", mission_type=MissionType.YOUTUBE,
                      departments=["media"], tasks=[task])
    plan = TaskPlan(mission.title)
    plan.add_task(task)
    ceo = CEO.__new__(CEO)
    ceo._capability_recovery_plans = {mission.id: (mission, plan)}
    monkeypatch.setattr("src.mission.recovery._task_genuinely_succeeded", lambda current: True)
    monkeypatch.setattr("src.mission.completion.evaluate_goal_completion",
                        lambda current: SimpleNamespace(missing=[]))

    outcome = ceo.resume_paid_media_approval(mission.id, task.id)

    assert outcome["status"] == "RESUMED"
    assert seen == ["paid_media_generation"]
    assert plan.get(task.id) is task and mission.tasks[0] is task
    assert "paid_media_permission" not in task.metadata
