"""Focused regression coverage for conditional recovery/safety routing.

All provider/search behavior is mocked or inspected before execution. No
network, paid media, publishing, installation, or worker call is made.
"""

from src.agents.media_agent import MediaAgent
from src.agents.research_agent import ResearchAgent
from src.config.settings import Settings
from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus
from src.media.production import GeneralProductionBuilder, ScenePlan
from src.mission.goal_spec import parse_goal_spec
from src.mission.mission_engine import MissionEngine
from src.mission.models import Mission, MissionType
from src.mission.recovery import MissionRecoveryReport
from src.mission.report_builder import build_ceo_report
from src.mission.target_resolver import TargetKind
from src.providers.aiml_media_provider import AIMLMediaProvider
from src.providers.fal_provider import FalMediaProvider
from src.providers.nvidia_provider import NvidiaMediaProvider


FULL_COMMAND = (
    "Jarvis, İsviçre pazarı için Swiss Insider kanalına uygun güncel ve güçlü bir konu araştır. "
    "En iyi konuyu seç ve YouTube Short videosunu üret. "
    "Gerekli bir yeteneğin eksik olduğunu fark edersen mevcut yeteneklerini ve sağlayıcılarını "
    "önce kontrol et; çözemezsen capability recovery sürecini kullan. "
    "Ücretli işlem, yeni hesap, kurulum, kod entegrasyonu veya yayınlama gerekiyorsa benden onay "
    "almadan gerçekleştirme. Videoyu YouTube'a yükleme veya yayınlama. "
    "Sonucu ve varsa gereken onayı bana bildir."
)


def _tasks():
    engine = MissionEngine()
    mission = engine.create_mission(FULL_COMMAND)
    return mission, engine.orchestrator.create_tasks(mission)


def test_full_command_routes_to_research_then_media_without_acquisition_departments():
    spec = parse_goal_spec(FULL_COMMAND)
    assert any("capability recovery" in row for row in spec.constraints)
    assert any("onay" in row for row in spec.constraints)
    assert any("yükleme" in row for row in spec.constraints)

    mission, tasks = _tasks()
    assert mission.departments == ["research", "media"]
    assert mission.target.kind == TargetKind.FREE_TEXT
    assert mission.target.category_hint is None
    assert "youtube automation" not in str(mission.target).casefold()
    assert [task.agent for task in tasks] == ["research", "media"]


def test_best_topic_is_not_repository_selection_and_research_query_is_clean():
    mission, tasks = _tasks()
    research = next(task for task in tasks if task.agent == "research")
    media = next(task for task in tasks if task.agent == "media")

    assert set(mission.departments) == {"research", "media"}
    assert research.id in media.depends_on
    assert media.metadata["research_task"] is research
    assert "İsviçre pazarı için" in research.target
    assert "güncel gündem" in research.target
    assert "capability recovery" not in research.target
    assert "sağlayıc" not in research.target
    assert "kod entegrasyonu" not in research.target
    assert "yayınlama" not in research.target
    assert ResearchAgent._clean_query(research.target)


class _CaptureMediaManager:
    last_artifact_path = ""
    last_production_record = None
    last_capability_gap = None

    def __init__(self):
        self.calls = []

    def set_channel_scope(self, channel_id):
        pass

    def plan(self, topic, duration_seconds=60, preferred_provider=None,
             produce_artifact=False, stage_sink=None, research_opportunity=None):
        self.calls.append({
            "topic": topic,
            "duration_seconds": duration_seconds,
            "preferred_provider": preferred_provider,
            "produce_artifact": produce_artifact,
            "stage_sink": stage_sink,
            "research_opportunity": research_opportunity,
        })
        return "SENARYO\nx\n\nSAHNELER\nx"


def _completed_research(report):
    task = Task(title="research", agent="research", handler=lambda task: "ok", metadata={"report": report})
    task.status = TaskStatus.COMPLETED
    task.result = TaskResult(success=True, output="ok")
    return task


def test_youtube_media_fails_closed_on_insufficient_research():
    media = Task(title="media", agent="media", target="Short üret", handler=lambda task: "ok", metadata={
        "research_task": _completed_research({"sufficient": False, "reason": "güncel kanıt yetersiz"}),
    })
    agent = MediaAgent()
    manager = _CaptureMediaManager()
    agent.manager = manager

    output = agent.execute(media)

    assert "RESEARCH_GAP" in output
    assert manager.calls == []


def test_youtube_media_uses_sufficient_existing_selected_opportunity():
    opportunity = {
        "selected_topic": "İsviçre'de bugün açıklanan enerji paketi",
        "location_or_market": "İsviçre pazarı için",
        "supporting_evidence": [{"url": "https://example.test/swiss", "title": "Swiss news"}],
        "freshness_status": "CURRENT", "sufficient": True, "reason": "", "why_current": "bugün",
    }
    media = Task(title="media", agent="media", target="Short üret", handler=lambda task: "ok", metadata={
        "research_task": _completed_research(opportunity),
    })
    agent = MediaAgent()
    manager = _CaptureMediaManager()
    agent.manager = manager

    agent.execute(media)

    assert manager.calls[0]["topic"] == opportunity["selected_topic"]
    assert manager.calls[0]["research_opportunity"] == opportunity


def test_all_ranked_paid_candidates_are_visible_but_none_are_called(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "configured-not-authorized")
    monkeypatch.setattr(Settings, "FAL_API_KEY", "configured-not-authorized")
    monkeypatch.setattr(Settings, "AIML_API_KEY", "configured-not-authorized")
    providers = [NvidiaMediaProvider(), FalMediaProvider(), AIMLMediaProvider()]
    ranked = [(provider.profiles()[0], provider) for provider in providers]
    monkeypatch.setattr(NvidiaMediaProvider, "generate_image", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("paid call")))
    monkeypatch.setattr(FalMediaProvider, "generate_image", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("paid call")))
    monkeypatch.setattr(AIMLMediaProvider, "generate_image", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("paid call")))
    scene = ScenePlan("scene-1", "beat-1", "hook", "narration", "Swiss city", 5.0, "cut")

    image, evidence = GeneralProductionBuilder._generate_scene_image(
        ranked, scene, 1, tmp_path, standing_permission=False,
    )

    assert image is None
    assert evidence.quality_evidence["approval_required"] is True
    assert "nvidia/" in evidence.quality_evidence["reason"]
    assert "fal/" in evidence.quality_evidence["reason"]
    assert "aiml/" in evidence.quality_evidence["reason"]


def test_approval_only_recovery_report_names_real_blocker_not_unknown():
    task = Task(title="media", agent="media", handler=lambda task: "ok")
    task.status = TaskStatus.FAILED
    mission = Mission(title="Short üret", mission_type=MissionType.YOUTUBE, departments=["media"], tasks=[task])
    blocker = "APPROVAL_REQUIRED: paid media generation for scene 1 needs approval"
    mission.recovery = MissionRecoveryReport(
        goal=mission.title, ran=True, blocked=True,
        approval_required=[{
            "task_id": task.id, "department": "media", "need": "Paid media approval", "why": blocker,
            "why_free_insufficient": "The capability exists; discovery is not an approval substitute.",
        }],
    )

    report = build_ceo_report(mission)

    assert blocker in report
    assert "NEYİN BAŞARISIZ OLMASI BENİ DURDURDU? bilinmiyor" not in report
    assert "capability discovery onayın yerine geçmez" in report
