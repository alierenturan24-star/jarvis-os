from __future__ import annotations

import pytest

from src.capabilities.sandbox_executor import CapabilitySandboxExecutor
from src.sandbox.models import SandboxResult, SandboxStatus


def proposal(repository="acme/tool"):
    return {"repository": repository, "reason": "static verification"}


def evaluation(repository="acme/tool", evidence_url="https://github.com/acme/tool"):
    return {"repository": repository, "confidence": .75, "risk_level": "MEDIUM",
            "recommended_action": "REQUEST_APPROVAL_FOR_SANDBOX",
            "jarvis_environment_compatibility": "COMPATIBLE", "license": {"license_name": "MIT"},
            "evidence": [{"url": evidence_url, "path": "README"}]}


class FakeManager:
    def __init__(self, status=SandboxStatus.READY_FOR_REVIEW, run_error=None, cleanup_error=None):
        self.status, self.run_error, self.cleanup_error = status, run_error, cleanup_error
        self.run_calls = 0; self.cleanup_calls = 0

    def run_pipeline(self, repository_url, repo_evaluation, repo=None, **kwargs):
        self.run_calls += 1
        if self.run_error: raise self.run_error
        return SandboxResult(repo.full_name, repository_url, sandbox_path="fixture", status=self.status)

    def cleanup(self, result):
        self.cleanup_calls += 1
        if self.cleanup_error: raise self.cleanup_error
        result.status = SandboxStatus.CLEANED
        return result


def test_success_maps_to_safe_outcome_and_always_cleans():
    manager = FakeManager(); result = CapabilitySandboxExecutor(manager).verify(proposal(), evaluation())
    assert result["success"] is True and result["status"] == "ready_for_review"
    assert manager.run_calls == manager.cleanup_calls == 1 and "sandbox_path" not in result


def test_pipeline_failure_maps_failed_and_cleans_returned_result():
    manager = FakeManager(SandboxStatus.FAILED)
    result = CapabilitySandboxExecutor(manager).verify(proposal(), evaluation())
    assert result["success"] is False and manager.cleanup_calls == 1


def test_cleanup_exception_fails_closed():
    manager = FakeManager(cleanup_error=OSError("sensitive detail"))
    result = CapabilitySandboxExecutor(manager).verify(proposal(), evaluation())
    assert result == {"success": False, "status": "failed", "error_type": "OSError",
                      "error": "Sandbox cleanup failed"}
    assert manager.cleanup_calls == 1


@pytest.mark.parametrize("candidate,evaluated,evidence", [
    ("acme/tool", "evil/tool", "https://github.com/evil/tool"),
    ("acme/tool", "acme/tool", "https://github.com/evil/tool"),
    ("https://example.test/acme/tool", "acme/tool", "https://github.com/acme/tool"),
])
def test_mismatched_or_arbitrary_repository_never_reaches_sandbox(candidate, evaluated, evidence):
    manager = FakeManager()
    result = CapabilitySandboxExecutor(manager).verify(proposal(candidate), evaluation(evaluated, evidence))
    assert result["success"] is False and result["error_type"] == "RuntimeError"
    assert manager.run_calls == manager.cleanup_calls == 0
