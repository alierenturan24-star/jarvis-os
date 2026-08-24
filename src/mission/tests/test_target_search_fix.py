from src.github.models import RepoData
from src.agents.research_agent import ResearchAgent
from src.jobs.task import Task
from src.mission.department_adapters import search_target_repositories
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.models import Mission, MissionType
from src.mission.target_resolver import TargetResolver


def _repo(name: str) -> RepoData:
    return RepoData(
        name=name, full_name=f"owner/{name}", url=f"https://github.com/owner/{name}",
        description="Autonomous LLM agent orchestration workflow", stars=1, forks=0, license="MIT",
        topics=["ai-agent", "llm", "orchestration", "workflow"],
        last_update="2026-01-01T00:00:00Z", language="Python", category="ai agent",
    )


class RecordingSearch:
    def __init__(self, named=(), category=()):
        self.named = list(named)
        self.category = list(category)
        self.calls = []

    def search_named_target(self, name, **kwargs):
        self.calls.append(("named", name))
        return list(self.named)

    def search(self, category, **kwargs):
        self.calls.append(("category", category))
        return list(self.category)

    @staticmethod
    def score(repo):
        return 50.0, 10.0


def test_exact_named_search_is_first_and_category_is_skipped_when_found():
    target = TargetResolver().resolve("Agent-Reach'i araştır.", MissionType.RESEARCH)
    intelligence = RecordingSearch(named=[_repo("agent-reach")])
    repos, query = search_target_repositories(intelligence, target, max_results=5)
    assert intelligence.calls == [("named", "Agent-Reach")]
    assert query == "Agent-Reach"
    assert repos[0].name == "agent-reach"


def test_category_fallback_occurs_only_after_exact_not_found():
    target = TargetResolver().resolve("Agent-Reach'i araştır.", MissionType.RESEARCH)
    intelligence = RecordingSearch(category=[_repo("agent-reach")])
    repos, query = search_target_repositories(intelligence, target, max_results=5)
    assert intelligence.calls == [("named", "Agent-Reach"), ("category", "ai agent")]
    assert query == "ai agent"
    assert repos[0].name == "agent-reach"


def test_named_target_and_short_browser_query_are_preserved_across_tasks():
    text = "Agent-Reach'i araştır ve Jarvis için gerçekten faydalıysa değerlendir."
    target = TargetResolver().resolve(text, MissionType.RESEARCH)
    mission = Mission(
        title=text, description=text, mission_type=MissionType.RESEARCH,
        departments=["research", "github", "browser", "evaluation"], target=target,
    )
    tasks = DepartmentOrchestrator(github_intelligence=RecordingSearch()).create_tasks(mission)
    assert all(task.metadata["target"] is target for task in tasks)
    browser = next(task for task in tasks if task.agent == "browser")
    assert browser.target == "Agent-Reach GitHub"
    assert browser.target != text


def test_research_cache_lookup_uses_named_target_not_general_prompt():
    class RecordingManager:
        def __init__(self):
            self.topics = []

        def research(self, topic, **kwargs):
            self.topics.append(topic)
            return "ok"

    text = "Agent-Reach'i araştır ve Jarvis için gerçekten faydalıysa değerlendir."
    target = TargetResolver().resolve(text, MissionType.RESEARCH)
    manager = RecordingManager()
    agent = ResearchAgent()
    agent.manager = manager
    task = Task(title=text, agent="research", target=text, metadata={"target": target})
    assert agent.execute(task) == "ok"
    assert manager.topics == ["Agent-Reach"]
