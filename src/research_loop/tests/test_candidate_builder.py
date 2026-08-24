from __future__ import annotations

from src.evaluation.models import RepoEvaluation
from src.github.models import RepoData
from src.jobs.task import Task
from src.mission.models import Mission
from src.research_loop.candidate_builder import build_candidates, evidence_urls


def _repo(full_name="owner/tool", url="https://github.com/owner/tool") -> RepoData:
    return RepoData(
        name="tool", full_name=full_name, url=url, description="d", stars=10, forks=1,
        license="mit", last_update="2026-01-01T00:00:00Z", language="Python", category="ai agent",
    )


def _evaluation(overall=80.0, risk="LOW") -> RepoEvaluation:
    return RepoEvaluation(
        name="tool", url="https://github.com/owner/tool", overall_score=overall,
        architecture_score=70, activity_score=70, community_score=70, license_score=100,
        security_score=90, compatibility_score=80, maintenance_score=70, relevance_score=85,
        recommendation="Uygun.", suitable_for_jarvis=True, target_module="src.tools",
        integration_difficulty="LOW", risk_level=risk,
    )


def _mission_with_ai_discovery(top: list[dict]) -> Mission:
    mission = Mission(title="hedef")
    task = Task(
        title="[ai_discovery]", agent="ai_discovery", target="hedef",
        metadata={"report": {"focus": "hedef", "total_found": len(top), "top": top}},
    )
    mission.tasks = [task]
    return mission


def _mission_with_evaluation(candidates: list[dict]) -> Mission:
    mission = Mission(title="hedef")
    task = Task(
        title="[evaluation]", agent="evaluation", target="hedef",
        metadata={"report": {"candidates": candidates}},
    )
    mission.tasks = [task]
    return mission


class TestBuildCandidatesFromAiDiscovery:
    def test_no_ai_discovery_task_returns_empty(self):
        mission = Mission(title="hedef")
        mission.tasks = []
        assert build_candidates(mission) == ()

    def test_no_top_results_returns_empty(self):
        mission = _mission_with_ai_discovery([])
        assert build_candidates(mission) == ()

    def test_maps_evolution_scorer_fields_without_reinventing_score(self):
        item = {
            "query": "q", "title": "Cool Tool", "url": "https://github.com/x/y",
            "summary": "s" * 10, "score": 77, "goal_fit": 60, "safety": 90,
            "implementation_ease": 75, "cost_advantage": 95, "expected_value": 80,
        }
        mission = _mission_with_ai_discovery([item])
        candidates = build_candidates(mission)
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.source == "ai_discovery"
        assert candidate.title == "Cool Tool"
        assert candidate.score == 77
        assert candidate.cost_advantage == 95

    def test_github_url_recommends_sandbox(self):
        item = {"query": "q", "title": "t", "url": "https://github.com/x/y", "summary": "s",
                 "score": 50, "goal_fit": 50, "safety": 50, "implementation_ease": 50,
                 "cost_advantage": 50, "expected_value": 50}
        mission = _mission_with_ai_discovery([item])
        assert "Sandbox" in build_candidates(mission)[0].recommendation

    def test_non_github_url_recommends_verifying_official_source_first(self):
        item = {"query": "q", "title": "t", "url": "https://huggingface.co/x", "summary": "s",
                 "score": 50, "goal_fit": 50, "safety": 50, "implementation_ease": 50,
                 "cost_advantage": 50, "expected_value": 50}
        mission = _mission_with_ai_discovery([item])
        assert "resmi kaynağından" in build_candidates(mission)[0].recommendation


class TestBuildCandidatesFromEvaluation:
    def test_maps_evaluation_engine_fields(self):
        entry = {"repo": _repo(), "evaluation": _evaluation(), "sandbox_verdict": "PASS", "integration_plan": None}
        mission = _mission_with_evaluation([entry])
        candidates = build_candidates(mission)
        assert len(candidates) == 1
        assert candidates[0].source == "evaluation"
        assert candidates[0].score == 80

    def test_missing_repo_or_evaluation_is_skipped_not_crashed(self):
        entry = {"repo": None, "evaluation": None, "sandbox_verdict": "?", "integration_plan": None}
        mission = _mission_with_evaluation([entry])
        assert build_candidates(mission) == ()

    def test_round_number_is_recorded(self):
        item = {"query": "q", "title": "t", "url": "u", "summary": "s", "score": 1,
                 "goal_fit": 1, "safety": 1, "implementation_ease": 1, "cost_advantage": 1, "expected_value": 1}
        mission = _mission_with_ai_discovery([item])
        candidate = build_candidates(mission, round_number=3)[0]
        assert candidate.round_number == 3


class TestEvidenceUrls:
    def test_collects_ai_discovery_and_github_urls(self):
        mission = Mission(title="hedef")
        ai_task = Task(title="a", agent="ai_discovery", target="x", metadata={
            "report": {"top": [{"url": "https://a.com"}, {"url": "https://b.com"}]}
        })
        github_task = Task(title="g", agent="github", target="x", metadata={
            "report": {"top": [{"repo": _repo(url="https://github.com/o/r")}]}
        })
        mission.tasks = [ai_task, github_task]
        urls = evidence_urls(mission)
        assert set(urls) == {"https://a.com", "https://b.com", "https://github.com/o/r"}

    def test_no_matching_tasks_returns_empty(self):
        mission = Mission(title="hedef")
        mission.tasks = []
        assert evidence_urls(mission) == ()
