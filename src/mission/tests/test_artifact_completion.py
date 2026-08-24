from pathlib import Path
import subprocess

from src.core.task_plan import TaskPlan
from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus
from src.mission.completion import evaluate_goal_completion, infer_completion_requirements
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.models import Mission, MissionStatus, MissionType
from src.mission.recovery import MissionRecoveryReport, plan_needs_recovery, recover_mission
from src.mission.report_builder import _recovery_section
from src.strategy.execution_planner import build_self_check


def _completed_task(agent="media", output="plan hazır", metadata=None, handler=lambda task: "ok"):
    task = Task(title=f"[{agent}] görev", agent=agent, handler=handler, metadata=metadata or {})
    task.status = TaskStatus.COMPLETED
    task.result = TaskResult(success=True, output=output)
    return task


def _mission(title, tasks, departments=None):
    mission = Mission(
        title=title, goal=title, mission_type=MissionType.MEDIA,
        departments=departments or [task.agent for task in tasks], tasks=tasks,
    )
    mission.completion_requirements = infer_completion_requirements(title, mission.departments)
    return mission


def _write(path: Path, content=None) -> str:
    if content is None:
        if path.suffix == ".mp4":
            from src.media.renderer import find_ffmpeg
            subprocess.run([
                find_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=blue:s=32x32:d=0.1",
                "-pix_fmt", "yuv420p", str(path),
            ], check=True, timeout=15)
            return str(path)
        content = b"real"
    path.write_bytes(content)
    return str(path)


def test_a_video_without_mp4_cannot_complete():
    task = _completed_task()
    mission = _mission("Video üret.", [task])
    plan = TaskPlan(mission.title)
    plan.add_task(task)

    report = DepartmentOrchestrator().dispatch(mission, plan)

    assert report.success is False
    assert mission.status == MissionStatus.INCOMPLETE


def test_b_technical_mp4_without_semantic_evidence_is_rejected(tmp_path):
    task = _completed_task(metadata={"artifact_paths": [_write(tmp_path / "video.mp4")]})
    assert not evaluate_goal_completion(_mission("Video üret.", [task])).satisfied


def test_dispatch_does_not_promote_technical_only_video(tmp_path):
    artifact = _write(tmp_path / "video.mp4")
    task = _completed_task(metadata={"artifact_path": artifact})
    mission = _mission("Video üret.", [task])
    plan = TaskPlan(mission.title)
    plan.add_task(task)

    report = DepartmentOrchestrator().dispatch(mission, plan)

    assert report.success is False
    assert mission.artifact_paths == []


def test_c_thumbnail_description_is_not_an_image():
    task = _completed_task(output="Thumbnail oluşturuldu: kırmızı, çarpıcı bir tasarım")
    assert not evaluate_goal_completion(_mission("Thumbnail oluştur.", [task])).satisfied


def test_d_nonempty_png_satisfies_image(tmp_path):
    task = _completed_task(metadata={"artifact_path": _write(tmp_path / "thumb.png")})
    assert evaluate_goal_completion(_mission("Thumbnail oluştur.", [task])).satisfied


def test_e_voiceover_without_audio_is_incomplete():
    assert not evaluate_goal_completion(_mission("Voiceover üret.", [_completed_task()])).satisfied


def test_f_nonempty_wav_satisfies_audio(tmp_path):
    task = _completed_task(metadata={"output_path": _write(tmp_path / "voice.wav")})
    assert evaluate_goal_completion(_mission("Voiceover üret.", [task])).satisfied


def test_g_research_does_not_require_video():
    mission = _mission("YouTube trendlerini araştır.", [_completed_task("research")], ["research"])
    assert mission.completion_requirements == ()
    assert evaluate_goal_completion(mission).satisfied


def test_h_explicit_repo_evaluation_requires_planned_evidence():
    tasks = [_completed_task(name) for name in ("research", "evaluation", "sandbox", "integration")]
    tasks[1].metadata["report"] = {"candidates": []}
    mission = _mission(
        "Bu GitHub reposunu araştır ve değerlendir, güvenli mi söyle.",
        tasks, ["research", "evaluation", "sandbox", "integration"],
    )
    assert not evaluate_goal_completion(mission).satisfied


def test_i_missing_artifact_retries_only_declared_local_producer(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(
        "src.media.quality.validate_media_goal_artifact",
        lambda path, goal="": SimpleNamespace(passed=True),
    )
    calls = {"research": 0, "media": 0}
    research = _completed_task("research", handler=lambda task: calls.__setitem__("research", calls["research"] + 1))

    def make_video(task):
        calls["media"] += 1
        task.metadata["artifact_paths"] = [_write(tmp_path / "recovered.mp4")]
        return "video kaydedildi"

    media = _completed_task("media", metadata={"artifact_recovery_available": True}, handler=make_video)
    mission = _mission("Video üret.", [research, media], ["research", "media"])
    plan = TaskPlan(mission.title)
    plan.add_task(research)
    plan.add_task(media)

    report = recover_mission(mission, plan)

    assert report.ran and not report.remaining_goals
    assert calls == {"research": 0, "media": 1}


def test_j_missing_artifact_without_safe_route_is_blocked():
    task = _completed_task()
    mission = _mission("Video üret.", [task])
    plan = TaskPlan(mission.title)
    plan.add_task(task)
    report = recover_mission(mission, plan)
    assert report.blocked and report.approval_required


def test_k_missing_artifact_prevents_self_check_100():
    check = build_self_check(_mission("Video üret.", [_completed_task()]), None)
    assert check.success_rate < 100
    assert check.artifact_statuses == ("MISSING",)


def test_l_recovery_remaining_never_says_nothing_for_missing_artifact():
    task = _completed_task()
    mission = _mission("Video üret.", [task])
    mission.recovery = MissionRecoveryReport(
        goal=mission.goal, ran=True, remaining_goals=["gerçek video üretimi"], blocked=True,
    )
    section = _recovery_section(mission)
    assert "NE KALDI? gerçek video üretimi" in section
    assert "NE KALDI? hiçbir şey" not in section


def test_m_completed_research_and_github_are_not_rerun_during_artifact_recovery(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(
        "src.media.quality.validate_media_goal_artifact",
        lambda path, goal="": SimpleNamespace(passed=True),
    )
    calls = {"research": 0, "github": 0}
    research = _completed_task("research", handler=lambda task: calls.__setitem__("research", 1))
    github = _completed_task("github", handler=lambda task: calls.__setitem__("github", 1))

    def media_handler(task):
        task.metadata["artifact_path"] = _write(tmp_path / "done.mp4")
        return "done"

    media = _completed_task("media", metadata={"artifact_recovery_available": True}, handler=media_handler)
    mission = _mission("Video üret.", [research, github, media], ["research", "github", "media"])
    plan = TaskPlan(mission.title)
    for task in mission.tasks:
        plan.add_task(task)
    recover_mission(mission, plan)
    assert calls == {"research": 0, "github": 0}


def test_n_zero_byte_mp4_is_rejected(tmp_path):
    empty = tmp_path / "empty.mp4"
    empty.touch()
    task = _completed_task(metadata={"artifact_path": str(empty)})
    assert not evaluate_goal_completion(_mission("Video üret.", [task])).satisfied


def test_o_existing_false_success_still_triggers_recovery():
    task = _completed_task(output="Ollama zaman aşımına uğradı.")
    mission = _mission("Trendleri araştır.", [task])
    plan = TaskPlan(mission.title)
    plan.add_task(task)
    assert plan_needs_recovery(plan, mission)


def test_p_capability_gap_discovers_then_uses_safe_mission_producer(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(
        "src.media.quality.validate_media_goal_artifact",
        lambda path, goal="": SimpleNamespace(passed=True),
    )
    calls = []

    class Collector:
        def collect(self, focus="", broad=True, **kwargs):
            calls.append((focus, broad))
            return [{"title": "local candidate", "url": "https://example.test/tool"}]

    def produce(task):
        task.metadata["artifact_path"] = _write(tmp_path / "continued.mp4")
        return "video artifact created"

    media = _completed_task()
    producer = Task(
        title="local renderer", agent="media", handler=produce,
        metadata={
            "provides_capabilities": ("media_artifact",),
            "safe_use_action": "video_draft",
        },
    )
    producer.status = TaskStatus.CANCELLED
    mission = _mission("Video üret.", [media, producer])
    mission.capability_gaps = ("media_artifact",)
    plan = TaskPlan(mission.title)
    plan.add_task(media)
    plan.add_task(producer)

    report = recover_mission(mission, plan, evolution_collector=Collector())

    assert calls and calls[0][1] is False
    assert report.discovery_runs[0].candidates
    assert report.used_candidates[0]["capability"] == "media_artifact"
    assert evaluate_goal_completion(mission).satisfied
    assert report.remaining_goals == []
    assert report.approval_required == []


def test_q_capability_candidate_survives_from_existing_task_report():
    task = _completed_task("github", metadata={
        "report": {"candidates": [{"title": "kept", "url": "https://example.test/kept"}]}
    })
    mission = _mission("Video üret.", [task])
    mission.capability_gaps = ("media_artifact",)
    plan = TaskPlan(mission.title)
    plan.add_task(task)

    class EmptyCollector:
        def collect(self, **kwargs):
            return []

    recover_mission(mission, plan, evolution_collector=EmptyCollector())

    assert [item["title"] for item in mission.capability_candidates] == ["kept"]
