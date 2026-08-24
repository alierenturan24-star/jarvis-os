from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.providers.claude_code_provider import ClaudeCodeEditResult, ClaudeCodeWorker
from src.security.action_policy import ActionPolicy

# JARVIS PRIORITY (Mode B, Claude Code repo-edit delegation): this adapter is
# the ONLY place ActionPolicy approval + test execution are decided for the
# edit-capable Claude Code path. ``ClaudeCodeWorker.run_edit`` (see
# ``src.providers.claude_code_provider``) stays policy-free -- it only knows
# how to run the CLI safely (allow-listed tools, no Bash, required cwd
# boundary). Test execution is run by JARVIS itself via a fixed subprocess
# call, never by giving Claude Code a shell tool -- destructive git actions
# stay architecturally impossible from inside the CLI subprocess.

_MAX_TEXT_CHARS = 4000
_DEFAULT_TEST_TIMEOUT_SECONDS = 120.0
_DEFAULT_TEST_COMMAND = ["py", "-3.13", "-m", "pytest", "-q"]

STATUS_DONE = "DONE"
STATUS_FAILED = "FAILED"
STATUS_BLOCKED = "BLOCKED"
STATUS_DONE_AWAITING_TEST_APPROVAL = "DONE_AWAITING_TEST_APPROVAL"


def _bounded(text: object, limit: int = _MAX_TEXT_CHARS) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[:limit] + "... [truncated]"


@dataclass
class ClaudeCodeEditOutcome:
    """Structured, Control-Center-shaped result of a delegated repo-edit
    attempt. ``to_dict()`` output is what ``CodingAgent``/observability
    consume -- deliberately plain/JSON-safe, no secrets (prompt/env are
    never included here)."""

    delegated_to: str
    status: str
    files_changed: tuple[str, ...]
    tests_executed: bool
    result_summary: str
    error_summary: Optional[str]
    approval_required: bool
    test_output: str = ""

    def to_dict(self) -> dict:
        return {
            "delegated_to": self.delegated_to,
            "status": self.status,
            "files_changed": list(self.files_changed),
            "files_changed_count": len(self.files_changed),
            "tests_executed": self.tests_executed,
            "result_summary": self.result_summary,
            "error_summary": self.error_summary,
            "approval_required": self.approval_required,
            "test_output": self.test_output,
        }


class ClaudeCodeEditAdapter:
    """Approval-gated orchestration for Mode B (repo-level coding/edit/test
    delegation to the locally installed Claude Code CLI). Reuses the
    existing ``ActionPolicy`` (``edit_project_file``/``run_project_tests``)
    -- does not invent a second approval mechanism."""

    def __init__(
        self,
        worker: Optional[ClaudeCodeWorker] = None,
        action_policy: Optional[ActionPolicy] = None,
    ) -> None:
        self.worker = worker or ClaudeCodeWorker()
        self.action_policy = action_policy or ActionPolicy()

    def delegate_edit(
        self,
        prompt: str,
        *,
        repo_path: Path,
        approved: bool = False,
        standing_permission: bool = False,
        run_tests: bool = False,
        test_command: Optional[list[str]] = None,
    ) -> ClaudeCodeEditOutcome:
        edit_decision = self.action_policy.evaluate(
            "edit_project_file", standing_permission=standing_permission,
        )
        if not edit_decision.allowed or (edit_decision.requires_confirmation and not approved):
            return ClaudeCodeEditOutcome(
                delegated_to="claude_code", status=STATUS_BLOCKED,
                files_changed=(), tests_executed=False,
                result_summary="Onay bekleniyor: dosya düzenleme işlemi.",
                error_summary=edit_decision.reason, approval_required=True,
            )

        if not self.worker.is_available():
            text = "Claude Code CLI kullanılamıyor (PATH'te bulunamadı veya giriş yapılmamış)."
            return ClaudeCodeEditOutcome(
                delegated_to="claude_code", status=STATUS_FAILED,
                files_changed=(), tests_executed=False,
                result_summary=text, error_summary=text, approval_required=False,
            )

        result: ClaudeCodeEditResult = self.worker.run_edit(prompt, cwd=repo_path)

        if not result.success:
            return ClaudeCodeEditOutcome(
                delegated_to="claude_code", status=STATUS_FAILED,
                files_changed=result.files_changed, tests_executed=False,
                result_summary=_bounded(result.output),
                error_summary=_bounded(result.stderr or result.output),
                approval_required=False,
            )

        if not run_tests:
            return ClaudeCodeEditOutcome(
                delegated_to="claude_code", status=STATUS_DONE,
                files_changed=result.files_changed, tests_executed=False,
                result_summary=_bounded(result.output), error_summary=None,
                approval_required=False,
            )

        test_decision = self.action_policy.evaluate(
            "run_project_tests", standing_permission=standing_permission,
        )
        if not test_decision.allowed or (test_decision.requires_confirmation and not approved):
            return ClaudeCodeEditOutcome(
                delegated_to="claude_code", status=STATUS_DONE_AWAITING_TEST_APPROVAL,
                files_changed=result.files_changed, tests_executed=False,
                result_summary=_bounded(result.output),
                error_summary="Onay bekleniyor: test çalıştırma.",
                approval_required=True,
            )

        tests_passed, test_output = self._run_tests(repo_path, test_command)
        return ClaudeCodeEditOutcome(
            delegated_to="claude_code", status=STATUS_DONE,
            files_changed=result.files_changed, tests_executed=True,
            result_summary=_bounded(result.output),
            error_summary=None if tests_passed else "Testler başarısız oldu.",
            approval_required=False, test_output=_bounded(test_output),
        )

    @staticmethod
    def _run_tests(repo_path: Path, test_command: Optional[list[str]]) -> tuple[bool, str]:
        """JARVIS'in KENDİ, sabit subprocess çağrısı -- Claude Code'a hiçbir
        zaman shell/Bash aracı verilmez, testler HER ZAMAN buradan
        çalıştırılır. ``shell=False``, argüman listesi, sınırlı timeout --
        ``ClaudeCodeWorker``'daki AYNI güvenli subprocess deseni."""

        command = test_command or _DEFAULT_TEST_COMMAND
        try:
            proc = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8",
                timeout=_DEFAULT_TEST_TIMEOUT_SECONDS, cwd=str(repo_path), shell=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as error:
            return False, f"Test çalıştırma hatası: {error}"

        combined = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
        return proc.returncode == 0, combined
