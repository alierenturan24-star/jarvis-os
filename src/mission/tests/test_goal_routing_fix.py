from src.agents.agent_result import AgentResult
from src.github.models import RepoData
from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus
from src.mission.completion import infer_completion_requirements
from src.mission.department import classify_mission_type
from src.mission.department_adapters import GitHubDepartmentAgent
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.mission_engine import MissionEngine
from src.mission.models import Mission, MissionType
from src.mission.report_builder import _sandbox_section
from src.mission.target_resolver import TargetResolver
from src.strategy.execution_planner import build_self_check
from src.strategy.models import TaskCategory
from src.strategy.strategy_engine import classify_task_category


def _repo(name: str, full_name: str) -> RepoData:
    return RepoData(
        name=name, full_name=full_name, url=f"https://github.com/{full_name}",
        description="test", stars=10, forks=1, license="MIT",
        last_update="2026-01-01T00:00:00Z", language="Python", category="ai agent",
    )


class _SearchOnly:
    def __init__(self, repos):
        self.repos = repos

    def search(self, *args, **kwargs):
        return list(self.repos)

    @staticmethod
    def score(repo):
        return 50.0, 10.0


class _NoStrategy:
    def plan(self, request):
        raise RuntimeError("disabled in routing test")


def test_a_negative_money_constraint_does_not_select_finance():
    departments = DepartmentOrchestrator().select_departments(
        "Agent-Reach reposunu araştır. Para harcama."
    )
    assert "finance" not in departments
    assert {"research", "github"}.issubset(departments)


def test_b_tool_cost_research_keeps_repo_primary_intent():
    departments = DepartmentOrchestrator().select_departments(
        "Agent-Reach maliyetini ve ücretsiz olup olmadığını araştır."
    )
    assert "finance" not in departments
    assert {"research", "github", "browser"}.issubset(departments)


def test_c_bitcoin_is_still_finance():
    assert classify_mission_type("Bitcoin neden düştü?") == MissionType.FINANCE


def test_d_paid_api_constraint_does_not_add_finance_to_video():
    departments = DepartmentOrchestrator().select_departments(
        "Ücretli API kullanmadan YouTube videosu üret."
    )
    assert "finance" not in departments


def test_e_named_target_rejects_unrelated_finance_search_result():
    target = TargetResolver().resolve(
        "Agent-Reach adlı açık kaynak projeyi ve GitHub reposunu değerlendir.",
        mission_type=MissionType.GITHUB,
    )
    orchestrator = DepartmentOrchestrator(github_intelligence=_SearchOnly([
        _repo("finance", "yorkeccak/finance")
    ]))
    assert target.requested_name == "Agent-Reach"
    assert orchestrator._resolve_evidence_repo(target) is None


def test_f_named_target_not_found_does_not_substitute_another_repo():
    target = TargetResolver().resolve(
        "Agent-Reach reposunu araştır.", mission_type=MissionType.GITHUB,
    )
    task = Task(
        title="Agent-Reach", agent="github", metadata={"target": target},
    )
    output = GitHubDepartmentAgent(_SearchOnly([_repo("finance", "yorkeccak/finance")])).execute(task)
    assert "repo bulunamadı" in output
    assert task.metadata["report"]["top"] == []
    assert "yorkeccak/finance" not in output


def test_g_missing_requested_evidence_prevents_self_check_100():
    text = "Agent-Reach GitHub reposunu bul, README incele, Evaluation ve Sandbox değerlendir."
    departments = ["research", "github", "browser", "evaluation", "sandbox"]
    tasks = []
    for name in departments:
        task = Task(title=name, agent=name, handler=lambda task: "ok")
        task.status = TaskStatus.COMPLETED
        task.result = TaskResult(success=True, output=AgentResult(agent=name, success=True, output="ok"))
        task.metadata["report"] = {}
        tasks.append(task)
    mission = Mission(title=text, departments=departments, tasks=tasks)
    mission.completion_requirements = infer_completion_requirements(text, departments)
    check = build_self_check(mission, None)
    assert check.success_rate < 100
    assert {"github", "readme", "evaluation", "sandbox"}.issubset(check.expected_outputs)


def test_h_unrun_sandbox_report_is_truthful():
    task = Task(title="sandbox", agent="sandbox", handler=lambda task: "ok")
    task.status = TaskStatus.COMPLETED
    task.result = TaskResult(success=True, output="ok")
    task.metadata["report"] = {"repo": None, "result": None}
    section = _sandbox_section(task)
    assert "bulunamadı" in section or "veri yok" in section or "çalıştırılmadı" in section
    assert "başarıyla" not in section.casefold()


def test_i_multiline_prompt_creates_one_mission_with_full_text():
    prompt = """Agent-Reach projesini araştır.
Son raporda:
AGENT-REACH:
EVALUATION:
KARAR:"""
    engine = MissionEngine(strategy_engine=_NoStrategy())
    mission = engine.create_mission(prompt)
    assert mission.title == prompt
    assert mission.description == prompt
    assert mission.target.requested_name == "Agent-Reach"


_LIVE_COMPOUND_VIDEO_REQUEST = (
    "İsviçre’de yaşayan Türkler için güncel ve kaynaklı bir konu bul. "
    "Başarılı videoların konu ve hikâye yapısını analiz et fakat içeriklerini kopyalama. "
    "Özgün kısa senaryo, yeni görseller, yeni kapak, telif güvenli müzik ve altyazıyla "
    "9:16 test videosu oluştur. Yayınlama; MP4 dosyasını, kapağı ve kalite sonucunu panelde göster."
)


def test_j_compound_research_then_create_video_dispatches_research_and_media():
    departments = DepartmentOrchestrator().select_departments(_LIVE_COMPOUND_VIDEO_REQUEST)

    assert "research" in departments
    assert "media" in departments
    assert "finance" not in departments


def test_k_compound_video_goal_is_not_misreported_as_standalone_vision():
    category, reason = classify_task_category(_LIVE_COMPOUND_VIDEO_REQUEST)

    assert category == TaskCategory.YOUTUBE
    assert "video" in reason.casefold()


def test_l_compound_video_task_depends_on_current_research_result():
    mission = MissionEngine(strategy_engine=_NoStrategy()).create_mission(_LIVE_COMPOUND_VIDEO_REQUEST)
    plan = MissionEngine(strategy_engine=_NoStrategy()).build_task_plan(mission)
    research = next(task for task in plan.all_tasks() if task.agent == "research")
    media = next(task for task in plan.all_tasks() if task.agent == "media")

    assert research.id in media.depends_on
    assert media.metadata["research_task"] is research
