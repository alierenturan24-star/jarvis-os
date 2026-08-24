from __future__ import annotations

from src.agents.claude_code_edit_adapter import ClaudeCodeEditAdapter, ClaudeCodeEditOutcome
from src.agents.coding_agent import CodingAgent
from src.planner.task import Task
from src.providers.provider_manager import RouteResult


class _FakeAdapter:
    def __init__(self, outcome: ClaudeCodeEditOutcome):
        self.outcome = outcome
        self.calls = []

    def delegate_edit(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.outcome


def _stub_text_route(agent):
    """Ensures the ordinary advisory path never reaches a real provider."""
    def route(prompt, task_type, **kwargs):
        return RouteResult("advisory output", "fake", "fake", "test", False, 0.0, True, ("fake",))
    agent.router.manager.route_and_generate = route


class TestC_CodingMissionSelectsClaudeCodeWhenAvailable:
    def test_repo_edit_metadata_invokes_the_edit_adapter(self, tmp_path):
        outcome = ClaudeCodeEditOutcome(
            delegated_to="claude_code", status="DONE", files_changed=("a.py",),
            tests_executed=False, result_summary="done", error_summary=None,
            approval_required=False,
        )
        adapter = _FakeAdapter(outcome)
        agent = CodingAgent(edit_adapter=adapter)
        _stub_text_route(agent)

        task = Task(
            agent="coding", action="edit", target="fix the bug",
            metadata={"coding_mode": "repo_edit", "repo_path": str(tmp_path)},
        )
        result = agent.execute(task)

        assert len(adapter.calls) == 1
        assert result == "done"
        assert task.metadata["delegated_to"] == "claude_code"
        assert task.metadata["files_changed"] == ["a.py"]


class TestD_NonEditCodingTaskNeverRoutesToClaudeCode:
    def test_ordinary_coding_task_uses_advisory_route_not_adapter(self, tmp_path):
        adapter = _FakeAdapter(ClaudeCodeEditOutcome(
            delegated_to="claude_code", status="DONE", files_changed=(),
            tests_executed=False, result_summary="should not be used",
            error_summary=None, approval_required=False,
        ))
        agent = CodingAgent(edit_adapter=adapter)
        _stub_text_route(agent)

        task = Task(agent="coding", action="write", target="write a function")
        result = agent.execute(task)

        assert adapter.calls == []
        assert result == "advisory output"

    def test_missing_repo_path_does_not_invoke_adapter(self):
        adapter = _FakeAdapter(ClaudeCodeEditOutcome(
            delegated_to="claude_code", status="DONE", files_changed=(),
            tests_executed=False, result_summary="x", error_summary=None,
            approval_required=False,
        ))
        agent = CodingAgent(edit_adapter=adapter)

        task = Task(agent="coding", action="edit", target="fix", metadata={"coding_mode": "repo_edit"})
        result = agent.execute(task)

        assert adapter.calls == []
        assert "repo_path" in result


class TestG_UnapprovedEditRemainsApprovalGated:
    """Uses the REAL ClaudeCodeEditAdapter (not a fake) so the ActionPolicy
    gate itself is exercised end to end -- the CLI worker must never be
    invoked when confirmation is required and not granted."""

    def test_unapproved_edit_is_blocked_before_worker_is_invoked(self, tmp_path):
        class _SpyWorker:
            def __init__(self):
                self.invoked = False

            def is_available(self):
                return True

            def run_edit(self, *a, **kw):
                self.invoked = True
                raise AssertionError("worker must not be invoked without approval")

        worker = _SpyWorker()
        adapter = ClaudeCodeEditAdapter(worker=worker)
        agent = CodingAgent(edit_adapter=adapter)

        task = Task(
            agent="coding", action="edit", target="fix the bug",
            metadata={"coding_mode": "repo_edit", "repo_path": str(tmp_path)},  # approved not set -> False
        )
        agent.execute(task)

        assert worker.invoked is False
        assert task.metadata["approval_required"] is True
        assert task.metadata["status"] == "BLOCKED"
