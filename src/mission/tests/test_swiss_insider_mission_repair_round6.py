"""Regression coverage for the real 2026-09-22 FREE_ONLY mission report.

The live report preserved safety (no paid media/publish) but lost the user's
7-day and DE/FR/IT evidence constraints in the research task, then mislabeled
the resulting research gap as a missing capability and searched unrelated
C2PA candidates.  All tests here are local/mocked: no network, paid media,
publishing, or real production call is made.
"""

from types import SimpleNamespace

from src.jobs.job_manager import JobManager
from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus
from src.mission.department_orchestrator import _media_research_query
from src.mission.failure_classification import FailureClass, classify_failure
from src.mission.mission_engine import MissionEngine
from src.mission.models import Mission, MissionType
from src.mission.recovery import MissionRecoveryReport, _continue_capability_gaps
from src.core.task_plan import TaskPlan
from src.research.collector import ResearchCollector
from src.research.summarizer import Summarizer


FULL_MISSION = (
    "Swiss Insider için İsviçre’nin son 7 gündeki gündemini Almanca, Fransızca ve "
    "İtalyanca tarihli güvenilir kaynaklarla doğrula. Yüksek ilgi gören videolardan "
    "yalnızca konu, hook, tempo ve hikâye yapısını öğren; hiçbir video, görüntü, ses "
    "veya kapağı kopyalama. En güçlü tek konuyu seçip özgün Almanca Shorts hazırla. "
    "Yalnız FREE_ONLY kullan: lisansı kaydedilmiş ücretsiz görseller, özgün yerel müzik, "
    "Almanca seslendirme, altyazı, yeni kapak ve FFmpeg ile 9:16 MP4 üret. Ücretli medya "
    "kullanma ve YouTube’a yükleme; MP4 ile kapağı Artifacts bölümünde onaya gönder."
)


def test_round6_exact_research_constraints_survive_task_derivation():
    query = _media_research_query(FULL_MISSION)

    assert "İsviçre" in query
    assert "son 7 gün" in query
    assert all(language in query for language in ("Almanca", "Fransızca", "İtalyanca"))
    assert "yayın tarihi" in query
    assert "güvenilir" in query
    assert "FREE_ONLY" not in query
    assert "FFmpeg" not in query
    assert "yükleme" not in query


def test_round6_orchestrator_uses_full_request_not_first_sentence_only():
    engine = MissionEngine()
    mission = engine.create_mission(FULL_MISSION)
    tasks = engine.orchestrator.create_tasks(mission)
    research = next(task for task in tasks if task.agent == "research")

    assert "son 7 gün" in research.target
    assert all(language in research.target for language in ("Almanca", "Fransızca", "İtalyanca"))
    assert research.metadata["market_context"] == "İsviçre"


class _CapturingNewsWeb:
    def __init__(self):
        self.news_queries = []

    def search_news(self, **kwargs):
        self.news_queries.append(kwargs["query"])
        return {"success": False}

    def search(self, **kwargs):
        return {"success": False}


def test_round6_swiss_news_search_targets_distinct_trusted_language_outlets():
    collector = ResearchCollector()
    web = _CapturingNewsWeb()
    collector.web = web

    collector.collect(_media_research_query(FULL_MISSION))

    joined = "\n".join(web.news_queries)
    assert "site:srf.ch" in joined and "site:nzz.ch" in joined
    assert "site:rts.ch" in joined and "site:letemps.ch" in joined
    assert "site:rsi.ch" in joined and "site:cdt.ch" in joined


def test_round6_summarizer_receives_date_language_publisher_and_exact_url():
    captured = {}

    class _Manager:
        def route_and_generate(self, **kwargs):
            captured["prompt"] = kwargs["prompt"]
            return SimpleNamespace(output="SEÇİLEN KONU: test")

    summarizer = Summarizer()
    summarizer.router = SimpleNamespace(manager=_Manager())
    summarizer.summarize("İsviçre son 7 gün", [{
        "title": "Aktuelle Meldung", "url": "https://srf.ch/news/example",
        "summary": "Somut haber", "published_at": "2026-09-22T10:00:00+00:00",
        "source_language": "de", "publisher": "SRF",
    }])

    prompt = captured["prompt"]
    assert "Yayın tarihi: 2026-09-22" in prompt
    assert "Kaynak dili: de" in prompt
    assert "Yayıncı: SRF" in prompt
    assert "https://srf.ch/news/example" in prompt


def test_round6_research_gap_is_evidence_not_capability_failure():
    assert classify_failure("RESEARCH_GAP: tarihli kaynak doğrulanamadı") is FailureClass.EVIDENCE_INSUFFICIENT


def test_round6_research_gap_never_launches_capability_discovery():
    media = Task(title="media", agent="media", handler=lambda task: "unused")
    media.status = TaskStatus.COMPLETED
    media.result = TaskResult(True, "RESEARCH_GAP: tarihli kaynak doğrulanamadı")
    media.metadata["last_stage"] = "research_gap_stop"
    mission = Mission(
        title=FULL_MISSION, goal=FULL_MISSION, mission_type=MissionType.YOUTUBE,
        departments=["research", "media"], tasks=[media], capability_gaps=("media_artifact",),
    )
    plan = TaskPlan(goal=FULL_MISSION)
    plan.add_task(media)

    class _MustNotRun:
        def collect(self, *args, **kwargs):
            raise AssertionError("capability discovery must not run for RESEARCH_GAP")

    report = MissionRecoveryReport(goal=FULL_MISSION, ran=True)
    _continue_capability_gaps(
        mission, plan, report, evolution_collector=_MustNotRun(), job_manager=JobManager(),
    )

    assert report.discovery_runs == []
