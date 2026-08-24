from __future__ import annotations

from src.agents.coding_agent import CodingAgent, _extract_target_paths
from src.planner.task import Task
from src.providers.provider_manager import RouteResult


class _FakeAdapter:
    """Never invoked in these tests -- the advisory path must not touch it."""

    def __init__(self):
        self.calls = []

    def delegate_edit(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        raise AssertionError("edit adapter must not be invoked for a read-only inspection task")


def _capture_route(agent):
    captured = {}

    def route(prompt, task_type, **kwargs):
        captured["prompt"] = prompt
        captured["task_type"] = task_type
        captured["kwargs"] = kwargs
        return RouteResult("advisory output", "claude_code", "claude_code", "test", False, 0.0, True, ("claude_code",))

    agent.router.manager.route_and_generate = route
    return captured


GOAL = (
    "Inspect the python file src/media/quality.py (read-only) and explain "
    "to JARVIS what it does and which quality gates it enforces. Do not "
    "modify any file."
)


class TestD_ExactUserTaskSurvivesIntoTheProviderPrompt:
    """Requirement 9.D: the exact task text (as it would arrive via
    Control Center -> mission -> CodingAgent) must appear verbatim in the
    prompt handed to ProviderManager, not be replaced by a generic
    coding-assistant prompt."""

    def test_literal_goal_text_appears_verbatim_in_prompt(self):
        agent = CodingAgent(edit_adapter=_FakeAdapter())
        captured = _capture_route(agent)

        task = Task(agent="coding", action="write", target=GOAL)
        agent.execute(task)

        assert GOAL in captured["prompt"]

    def test_preferred_provider_hint_is_forwarded(self):
        agent = CodingAgent(edit_adapter=_FakeAdapter())
        captured = _capture_route(agent)

        task = Task(
            agent="coding", action="write", target=GOAL,
            metadata={"preferred_ai_provider": "claude_code"},
        )
        agent.execute(task)

        assert captured["kwargs"]["preferred_provider"] == "claude_code"


class TestE_TargetFilePathSurvivesDelegation:
    """Requirement 9.E: a concrete target file/path mentioned in the goal
    must be extracted and called out explicitly in the prompt."""

    def test_extract_target_paths_finds_the_file(self):
        assert "src/media/quality.py" in _extract_target_paths(GOAL)

    def test_extract_target_paths_ignores_text_with_no_path(self):
        assert _extract_target_paths("explain the coding department in general") == []

    def test_prompt_calls_out_the_target_path_explicitly(self):
        agent = CodingAgent(edit_adapter=_FakeAdapter())
        captured = _capture_route(agent)

        task = Task(agent="coding", action="write", target=GOAL)
        agent.execute(task)

        assert "src/media/quality.py" in captured["prompt"]


class TestF_ReadOnlyInspectionNeverBecomesRepoEdit:
    """Requirement 9.F: an ordinary inspection task (no coding_mode set)
    must stay on the advisory/read-only path -- never the repo_edit
    adapter -- and the prompt itself must say so explicitly."""

    def test_no_coding_mode_metadata_never_invokes_edit_adapter(self):
        agent = CodingAgent(edit_adapter=_FakeAdapter())
        _capture_route(agent)

        task = Task(agent="coding", action="write", target=GOAL)
        agent.execute(task)  # must not raise via the fake adapter

        assert agent.edit_adapter.calls == []

    def test_coding_mode_metadata_is_never_mutated_to_repo_edit(self):
        agent = CodingAgent(edit_adapter=_FakeAdapter())
        _capture_route(agent)

        task = Task(agent="coding", action="write", target=GOAL)
        agent.execute(task)

        assert task.metadata.get("coding_mode") != "repo_edit"

    def test_prompt_states_read_only_intent_explicitly(self):
        agent = CodingAgent(edit_adapter=_FakeAdapter())
        captured = _capture_route(agent)

        task = Task(agent="coding", action="write", target=GOAL)
        agent.execute(task)

        assert "SALT-OKUNUR" in captured["prompt"] or "read-only" in captured["prompt"]
        assert "repo_edit DEĞİL" in captured["prompt"]


class TestJ_NoFileChangesDuringReadOnlyDelegation:
    """Requirement 9.J: exercising the real advisory path end to end must
    never touch the filesystem -- proven by asserting the edit adapter
    (the only code path capable of writing) is categorically unreachable."""

    def test_full_advisory_execution_never_reaches_any_write_capable_path(self):
        agent = CodingAgent(edit_adapter=_FakeAdapter())
        _capture_route(agent)

        task = Task(agent="coding", action="write", target=GOAL, metadata={})
        result = agent.execute(task)

        assert agent.edit_adapter.calls == []
        assert result == "advisory output"
