from __future__ import annotations

from src.agents.coding_agent import CODING_MODE_REPO_EDIT
from src.jobs.task import Task
from src.mission.department_adapters import DepartmentAdapterRegistry

# Sprint: bounded Claude Code capability-build delegation (Phase 6). This is
# ONLY the previously-missing caller that supplies repo_path/approved to the
# ALREADY-BUILT repo-edit path (src.agents.coding_agent.CodingAgent ->
# src.agents.claude_code_edit_adapter.ClaudeCodeEditAdapter ->
# src.providers.claude_code_provider.ClaudeCodeWorker.run_edit). No new
# execution engine, no new tool permissions: Bash stays categorically
# excluded by ClaudeCodeWorker.run_edit's existing --allowedTools allowlist,
# and ActionPolicy still gates edit_project_file/run_project_tests exactly
# as it does today. This function builds the Task; it does not run it and
# is not wired into any automatic mission dispatch -- a caller (e.g. a
# Control Center action, once a capability has already passed the existing
# INTEGRATION_APPROVAL_REQUIRED human-approval gate) must explicitly hand
# the returned Task to JobManager.


def delegate_capability_build(
    capability_id: str, repo_path: str, *, approved: bool, run_tests: bool = True,
    standing_permission: bool = False, adapter_registry: DepartmentAdapterRegistry | None = None,
) -> Task:
    """Build a bounded, repo-edit-mode coding Task that lets JARVIS delegate
    a capability-integration build/adapter task to Claude Code through the
    existing, already-approval-gated architecture. ``approved`` must already
    reflect a real, prior human approval decision -- this function performs
    no approval decision of its own."""

    registry = adapter_registry or DepartmentAdapterRegistry()
    return Task(
        title=f"capability build: {capability_id}",
        agent="coding",
        target=f"Integrate approved capability {capability_id!r} into its matching existing provider interface.",
        handler=registry.resolve("coding"),
        metadata={
            "coding_mode": CODING_MODE_REPO_EDIT,
            "repo_path": repo_path,
            "approved": bool(approved),
            "standing_permission": bool(standing_permission),
            "run_tests": bool(run_tests),
            "capability_id": capability_id,
        },
    )
