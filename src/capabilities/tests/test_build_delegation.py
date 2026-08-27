from __future__ import annotations

from pathlib import Path

from src.agents.claude_code_edit_adapter import ClaudeCodeEditOutcome
from src.agents.coding_agent import CODING_MODE_REPO_EDIT, CodingAgent
from src.capabilities.build_delegation import delegate_capability_build
from src.mission.department_adapters import DepartmentAdapterRegistry

_ALLOWED_CODING_MODES = frozenset({"repo_edit"})  # mirrors ControlCenterService._CODING_MODE_ALLOWLIST


class _FakeAdapter:
    def __init__(self, outcome: ClaudeCodeEditOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple] = []

    def delegate_edit(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.outcome


def test_delegate_capability_build_produces_a_repo_edit_task(tmp_path):
    task = delegate_capability_build("cap-1", str(tmp_path), approved=True)

    assert task.agent == "coding"
    assert task.metadata["coding_mode"] == CODING_MODE_REPO_EDIT
    assert task.metadata["coding_mode"] in _ALLOWED_CODING_MODES
    assert task.metadata["repo_path"] == str(tmp_path)
    assert task.metadata["approved"] is True
    assert task.metadata["capability_id"] == "cap-1"
    assert task.handler is not None


def test_delegate_capability_build_routes_through_existing_repo_edit_path(tmp_path):
    outcome = ClaudeCodeEditOutcome(
        delegated_to="claude_code", status="DONE", files_changed=("adapter.py",),
        tests_executed=True, result_summary="adapter built", error_summary=None,
        approval_required=False,
    )
    fake_adapter = _FakeAdapter(outcome)
    registry = DepartmentAdapterRegistry(agents={"coding": CodingAgent(edit_adapter=fake_adapter)})

    task = delegate_capability_build(
        "cap-1", str(tmp_path), approved=True, run_tests=True, adapter_registry=registry,
    )
    result = task.handler(task)  # AgentResult -- to_handler() wraps CodingAgent.execute()

    assert len(fake_adapter.calls) == 1
    _, kwargs = fake_adapter.calls[0]
    assert kwargs["repo_path"] == Path(str(tmp_path))
    assert kwargs["approved"] is True
    assert kwargs["run_tests"] is True
    assert result.success is True and result.output == "adapter built"
    assert task.metadata["delegated_to"] == "claude_code"


def test_unapproved_build_never_invokes_the_worker(tmp_path):
    """Mirrors the existing approval-gate test pattern
    (src/agents/tests/test_coding_agent_edit_routing.py) -- approved=False
    must still block before the CLI worker is ever invoked."""

    class _SpyWorker:
        def is_available(self): return True
        def run_edit(self, *a, **kw): raise AssertionError("worker must not be invoked without approval")

    from src.agents.claude_code_edit_adapter import ClaudeCodeEditAdapter
    registry = DepartmentAdapterRegistry(
        agents={"coding": CodingAgent(edit_adapter=ClaudeCodeEditAdapter(worker=_SpyWorker()))},
    )

    task = delegate_capability_build("cap-1", str(tmp_path), approved=False, adapter_registry=registry)
    task.handler(task)

    assert task.metadata["approval_required"] is True
