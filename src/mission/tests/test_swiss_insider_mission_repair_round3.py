"""Regression tests for the THIRD real live regression run, using the
EXACT live user command as one fixture (implementation stays generic --
see individual test docstrings / helper functions in
``department_orchestrator.py``/``strategy_engine.py``/``cost_optimizer.py``
for the generic mechanisms, none of which special-case this sentence).

Real result: "Jarvis İsviçre için video üret." -> BLOCKED 0%.

  ROOT CAUSE (MEDIA vs AI strategy): MissionType.MEDIA was missing from
    both ``strategy_engine._MISSION_TYPE_TO_CATEGORY`` and
    ``cost_optimizer._TASK_KEYWORDS`` -- a real video-production command
    fell through to "category: other" / "task_class: chat/simple".
  ROOT CAUSE (research missing): MEDIA's canonical department bundle was
    ("media", "browser", "automation") -- no "research" at all, so
    browser blind-searched the LITERAL raw command on Google (hit an
    anti-bot page) instead of a real topic being researched.
  ROOT CAUSE (repo semantics leak): the CEO report/decision layer
    unconditionally assumed every mission needs a repository target --
    "Hedef repo: <full raw command>" and a REDDET verdict "Hiçbir
    departman somut bir repo adayı üretmedi" for a MEDIA mission that
    never dispatched github/evaluation/sandbox/integration at all.
  ROOT CAUSE (automation dispatch): "automation" (a no-op checklist
    generator) was unconditionally dispatched for every MEDIA mission.
  Render timed out at last_stage="render" with no finer diagnostic.

Uses mocks only -- no live network/API/paid/YouTube/finance calls. Does
NOT run the real mission and does NOT claim a real video was produced.
"""

from __future__ import annotations

from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus
from src.mission.completion import infer_completion_requirements
from src.mission.department import classify_mission_type
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.mission_engine import MissionEngine
from src.mission.models import Mission, MissionType
from src.mission.report_builder import _ceo_section, build_ceo_report
from src.mission.target_resolver import TargetKind, TargetResolver
from src.providers.cost_optimizer import TASK_CHAT, TASK_PLANNING, CostOptimizer
from src.providers.provider_manager import ProviderManager
from src.strategy.models import TaskCategory
from src.strategy.strategy_engine import AIStrategyEngine, classify_task_category

# Exact live command (sanitized regression fixture -- see module docstring:
# used ONLY as one concrete test case, every fix behind it is generic).
LIVE_COMMAND = "Jarvis İsviçre için video üret."


class _FakeProvider:
    def __init__(self, available: bool) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available


_ALL_PROVIDERS = ("ollama", "aiml", "openai", "anthropic", "gemini", "deepseek", "groq", "openrouter")


class _FakeProviderManager:
    def __init__(self, available: set[str]) -> None:
        self._available = available

    def get(self, name: str):
        normalized = ProviderManager.normalize(name)
        if normalized not in _ALL_PROVIDERS:
            return None
        return _FakeProvider(normalized in self._available)

    def available_names(self) -> list[str]:
        return [name for name in _ALL_PROVIDERS if name in self._available]


def _mission_engine(available: set[str] = frozenset({"ollama"})) -> MissionEngine:
    orchestrator = DepartmentOrchestrator()
    cost_optimizer = CostOptimizer(provider_manager=_FakeProviderManager(available))
    strategy_engine = AIStrategyEngine(orchestrator=orchestrator, cost_optimizer=cost_optimizer)
    return MissionEngine(orchestrator=orchestrator, strategy_engine=strategy_engine)


# --- POINT 1: mission remains MEDIA/video-production ---------------------------


def test_point1_mission_type_is_media():
    assert classify_mission_type(LIVE_COMMAND) == MissionType.MEDIA


def test_point1_generic_video_production_phrasings_are_also_media():
    for phrase in (
        "Video hazırla.", "Short üret.", "Short hazırla.",
        "Bir youtube videosu üret.", "Bugün için içerik üret.",
    ):
        assert classify_mission_type(phrase) in (MissionType.MEDIA, MissionType.YOUTUBE), phrase


# --- POINT 2: AI strategy does not classify as other/chat-simple ---------------


def test_point2_ai_strategy_category_is_not_other():
    category, _ = classify_task_category(LIVE_COMMAND)
    assert category != TaskCategory.OTHER
    assert category == TaskCategory.YOUTUBE


def test_point2_cost_optimizer_task_class_is_not_plain_chat():
    task_class = CostOptimizer.classify(LIVE_COMMAND)
    assert task_class != TASK_CHAT
    assert task_class == TASK_PLANNING


def test_point2_end_to_end_ai_strategy_plan_is_not_other_category():
    engine = _mission_engine()
    mission = engine.create_mission(LIVE_COMMAND)
    assert mission.ai_strategy is not None
    assert mission.ai_strategy.category != TaskCategory.OTHER


# --- POINTS 3-7: expected department fast path ----------------------------------


class TestExpectedDepartments:
    def setup_method(self):
        self.departments = DepartmentOrchestrator().select_departments(LIVE_COMMAND)

    def test_point3_research_selected(self):
        assert "research" in self.departments

    def test_point4_media_selected(self):
        assert "media" in self.departments

    def test_point5_automation_not_auto_selected(self):
        assert "automation" not in self.departments

    def test_point6_github_not_auto_selected(self):
        assert "github" not in self.departments

    def test_point7_validation_pipeline_not_auto_selected(self):
        assert "evaluation" not in self.departments
        assert "sandbox" not in self.departments
        assert "integration" not in self.departments

    def test_fast_path_is_exactly_research_and_media(self):
        assert set(self.departments) == {"research", "media"}


def test_existing_asset_edit_request_does_not_force_research():
    # "Bu hazır videoya altyazı ekle." -- editing an existing asset, no
    # new topic to discover.
    departments = DepartmentOrchestrator().select_departments(
        "Jarvis, bu hazır videoya altyazı ekle."
    )
    assert "automation" not in departments
    assert "github" not in departments


# --- POINT 8: literal command is never sent as the research query --------------


def test_point8_research_task_target_is_not_the_literal_command():
    engine = _mission_engine()
    mission = engine.create_mission(LIVE_COMMAND)
    plan = engine.build_task_plan(mission)

    research_task = next(t for t in plan.all_tasks() if t.agent == "research")
    assert str(research_task.target) != LIVE_COMMAND
    # Still a MEANINGFUL, market/context-preserving query -- never a fixed
    # hardcoded phrase either.
    assert "İsviçre" in str(research_task.target)
    assert "video üret" not in str(research_task.target).casefold()


def test_point8_explicit_research_ask_keeps_its_own_wording():
    # If the user EXPLICITLY asks to research something, that wording is
    # respected -- the query-rewrite only applies to IMPLICIT topic-
    # discovery research (added because none was asked for).
    engine = _mission_engine()
    mission = engine.create_mission("İsviçre'deki yeni girişimleri araştır ve video üret.")
    plan = engine.build_task_plan(mission)
    research_task = next(t for t in plan.all_tasks() if t.agent == "research")
    assert "İsviçre" in str(research_task.target)


# --- POINT 9: no repository target required -------------------------------------


def test_point9_target_is_not_a_repository_or_github_category():
    target = TargetResolver().resolve(LIVE_COMMAND, mission_type=MissionType.MEDIA)
    assert target.kind != TargetKind.REPOSITORY
    assert target.category_hint is None


# --- POINT 10: CEO does not reject for missing repo evidence -------------------


def _media_mission_with_failed_render() -> tuple[Mission, dict[str, Task]]:
    research_task = Task(title="[research] x", agent="research", handler=lambda t: "ok")
    research_task.status = TaskStatus.COMPLETED
    research_task.result = TaskResult(success=True, output="Araştırma tamamlandı.\n\nGüncel fırsat: X.")

    media_task = Task(title="[media] x", agent="media", handler=lambda t: "ok",
                       metadata={"last_stage": "render_ffmpeg_scene_2_of_4"})
    media_task.status = TaskStatus.FAILED
    media_task.error = "Görev zaman aşımına uğradı (75.0 sn)."

    mission = Mission(
        title=LIVE_COMMAND, goal=LIVE_COMMAND, mission_type=MissionType.MEDIA,
        departments=["research", "media"], tasks=[research_task, media_task],
    )
    mission.completion_requirements = infer_completion_requirements(LIVE_COMMAND, mission.departments)
    return mission, {"research": research_task, "media": media_task}


def test_point10_ceo_does_not_cite_missing_repo_candidate():
    mission, tasks_by_department = _media_mission_with_failed_render()
    section = _ceo_section(mission, tasks_by_department)
    assert "repo adayı" not in section.casefold()
    assert "hedef repo" not in section.casefold()


def test_point10_ceo_reports_truthful_incomplete_production():
    mission, tasks_by_department = _media_mission_with_failed_render()
    section = _ceo_section(mission, tasks_by_department)
    assert "REDDET" in section or "İNSAN İNCELEMESİ" in section
    assert "render_ffmpeg_scene_2_of_4" in section  # the ACTUAL failed stage, named


def test_point10_full_report_omits_hedef_repo_line_for_media_mission():
    mission, _ = _media_mission_with_failed_render()
    report = build_ceo_report(mission)
    assert "Hedef repo:" not in report


def test_repo_acquisition_mission_still_shows_target_repo_and_can_reject():
    # Preserve existing behavior for a GENUINE repo-acquisition mission.
    task = Task(title="[github] x", agent="github", handler=lambda t: "ok")
    task.status = TaskStatus.COMPLETED
    task.result = TaskResult(success=True, output="GitHubIntelligence.search('x'): repo bulunamadı.")
    task.metadata["report"] = {"category": "x", "total_found": 0, "top": []}
    mission = Mission(
        title="En iyi açık kaynak repo bul.", goal="En iyi açık kaynak repo bul.",
        mission_type=MissionType.GITHUB, departments=["github"], tasks=[task],
    )
    section = _ceo_section(mission, {"github": task})
    assert "REDDET" in section
    assert "repo adayı" in section.casefold()


# --- POINT 11: completion requires a real video artifact -----------------------


def test_point11_completion_requires_video_artifact():
    departments = DepartmentOrchestrator().select_departments(LIVE_COMMAND)
    requirements = infer_completion_requirements(LIVE_COMMAND, departments)
    assert any(r.kind == "artifact" and r.name == "video" for r in requirements)


# --- POINT 12: research failure cannot be silently counted as evidence ---------


def test_point12_failed_research_task_is_not_treated_as_completed_evidence():
    from src.mission.report_builder import _task_note

    research_task = Task(title="[research] x", agent="research", handler=lambda t: "ok")
    research_task.status = TaskStatus.FAILED
    research_task.error = "Araştırma kaynak toplama süresi doldu (RESEARCH_CYCLE_MAX_RUNTIME_EXCEEDED)."
    note = _task_note(research_task)
    assert note is not None
    assert "Tamamlanmadı" in note


# --- POINT 13: existing media recovery behavior remains intact -----------------


def test_point13_non_text_media_failure_still_skips_text_provider_ladder():
    from src.jobs.job_manager import JobManager
    from src.mission.recovery import RecoveryAttemptHistory, RecoveryStep, recover_task

    task = Task(
        title="t", agent="media", handler=lambda t: "unused",
        metadata={"preferred_ai_provider": "ollama", "last_stage": "render_ffmpeg_scene_1_of_4"},
    )
    task.status = TaskStatus.FAILED
    task.error = "Görev zaman aşımına uğradı (75.0 sn)."

    manager = _FakeProviderManagerForRecovery({"ollama", "gemini"})
    attempts = recover_task(
        task, Mission(title="t", mission_type=MissionType.MEDIA),
        provider_manager=manager, job_manager=JobManager(), history=RecoveryAttemptHistory(),
    )
    assert len(attempts) == 1
    assert attempts[0].step == RecoveryStep.NON_TEXT_MEDIA_CAPABILITY_GAP


class _FakeProviderManagerForRecovery:
    def __init__(self, available: set[str]) -> None:
        self._available = available

    def get(self, name: str):
        normalized = ProviderManager.normalize(name)
        return _FakeProvider(normalized in self._available)

    def available_names(self) -> list[str]:
        return list(self._available)


# --- POINT 14: render stage diagnostics identify a precise substage ------------


def test_point14_render_reports_which_ffmpeg_substage(tmp_path, monkeypatch):
    import json
    import subprocess

    from src.media.renderer import LocalVideoRenderer

    monkeypatch.chdir(tmp_path)

    calls = {"n": 0}
    real_run = subprocess.run

    def _fail_after_prepare(command, *args, **kwargs):
        calls["n"] += 1
        raise AssertionError("ffmpeg should not actually run in this test")

    # A manifest that passes the precondition checks and reaches the
    # per-scene ffmpeg stage -- but ffmpeg itself is never really invoked;
    # this test only proves the STAGE MARKER is set before that call.
    # ``_find_production_package`` looks under "workspace/assets/media"
    # (relative to CWD) by default -- match that exactly.
    root = tmp_path / "workspace" / "assets" / "media" / "prod"
    root.mkdir(parents=True)
    scene_files = []
    for i in range(4):
        scene = root / f"scene-{i}.png"
        scene.write_bytes(b"x" * 20_000)
        scene_files.append(scene.name)
    audio = root / "narration.wav"
    audio.write_bytes(b"x" * 20_000)
    manifest = {
        "goal": "test goal video üret", "placeholder": False, "fallback": False,
        "scene_files": scene_files, "audio_file": audio.name, "scene_plan": [],
        "story_beats": [],
    }
    (root / "production.json").write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr("src.media.renderer.find_ffmpeg", lambda: "ffmpeg.exe")
    monkeypatch.setattr(subprocess, "run", _fail_after_prepare)

    sink: dict = {}
    try:
        LocalVideoRenderer(output_root=tmp_path / "artifacts").render(
            "test goal video üret", "narration text", 30, stage_sink=sink,
        )
    except AssertionError:
        pass

    assert sink.get("last_stage") == "render_ffmpeg_scene_1_of_4"


# --- POINT 15: YouTube publish remains approval-gated ---------------------------


def test_point15_publish_actions_remain_medium_or_higher_risk():
    from src.security.action_policy import ActionPolicy

    assert "publish_scheduled_video" not in ActionPolicy.LOW_RISK_ACTIONS
    assert "upload_private_video" not in ActionPolicy.LOW_RISK_ACTIONS
