from __future__ import annotations

import json
import subprocess

from src.agents.coding_agent import CodingAgent
from src.planner.task import Task
from src.providers.claude_code_provider import ClaudeCodeProvider

GOAL = (
    "Inspect the python file src/media/quality.py (read-only) and explain "
    "to JARVIS what it does and which quality gates it enforces. Do not "
    "modify any file."
)


def _completed_success(result_text="Gerçek incelemenin cevabı."):
    payload = json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "result": result_text, "session_id": "sess-x", "total_cost_usd": 0.0,
    })
    return subprocess.CompletedProcess(args=["claude"], returncode=0, stdout=payload, stderr="")


class TestReadOnlyDelegationEndToEnd:
    """Requirements 9.D/E/F/G/J exercised together through the REAL
    CodingAgent -> ProviderManager -> ClaudeCodeProvider -> ClaudeCodeWorker
    chain (only the CLI subprocess itself is faked) -- proves the fix holds
    at the actual integration boundary, not just at each unit in isolation."""

    def test_real_chain_sends_full_task_in_plan_mode_with_no_write_tools(self, monkeypatch):
        captured = {}

        def _fake_run(command, **kwargs):
            captured["command"] = command
            captured["cwd"] = kwargs.get("cwd")
            captured["shell"] = kwargs.get("shell")
            return _completed_success()

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        agent = CodingAgent()
        agent.router.manager._providers = {"claude_code": ClaudeCodeProvider()}

        task = Task(
            agent="coding", action="write", target=GOAL,
            metadata={"preferred_ai_provider": "claude_code"},
        )
        result = agent.execute(task)

        assert result == "Gerçek incelemenin cevabı."

        command = captured["command"]
        # The exact concrete task (D) and target file (E) reached the CLI
        # invocation itself, not just an intermediate object.
        prompt = command[command.index("-p") + 1]
        assert GOAL in prompt
        assert "src/media/quality.py" in prompt

        # Read-only mode (F): plan mode only, no edit-capable flags at all.
        idx = command.index("--permission-mode")
        assert command[idx + 1] == "plan"
        assert "--allowedTools" not in command
        assert "acceptEdits" not in command

        # No fallback needed (G) and never any Bash/shell wrapping (J).
        assert task.metadata.get("coding_mode") != "repo_edit"
        assert captured["shell"] is not True
