from __future__ import annotations

from src.control_center.service import ControlCenterService
from src.control_center.store import ControlCenterStore
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.models import Mission


def _service(tmp_path):
    return ControlCenterService(store=ControlCenterStore(tmp_path / "state.json"))


class TestA_BackwardCompatibility:
    """Old /api/command-shaped requests (no execution_hints at all) must
    behave exactly as before."""

    def test_submit_command_without_hints_still_works(self, tmp_path):
        current = _service(tmp_path)
        mission = current.submit_command("piyasayı tara")
        assert mission["goal"] == "piyasayı tara"
        assert mission["status"] in {"QUEUED", "WORKING"}

    def test_validate_execution_hints_of_none_is_empty(self, tmp_path):
        assert _service(tmp_path)._validate_execution_hints(None) == {}


class TestB_PreferredProviderHintValidation:
    def test_claude_code_is_accepted(self, tmp_path):
        cleaned = _service(tmp_path)._validate_execution_hints({"preferred_ai_provider": "claude_code"})
        assert cleaned == {"preferred_ai_provider": "claude_code"}

    def test_alias_is_normalized(self, tmp_path):
        # "claude" is an existing ProviderManager alias for "anthropic" --
        # the hint must go through the SAME normalize() as every other
        # provider lookup, not a second parsing rule.
        cleaned = _service(tmp_path)._validate_execution_hints({"preferred_ai_provider": "claude"})
        assert cleaned == {"preferred_ai_provider": "anthropic"}


class TestC_CodingModeReachesTaskMetadata:
    def test_hints_apply_only_to_coding_department_task(self):
        orchestrator = DepartmentOrchestrator()
        mission = Mission(
            title="fix it", description="fix it", departments=["coding", "finance"],
            execution_hints={"preferred_ai_provider": "claude_code", "coding_mode": "repo_edit"},
        )
        tasks = orchestrator.create_tasks(mission)

        coding_task = next(t for t in tasks if t.agent == "coding")
        assert coding_task.metadata["preferred_ai_provider"] == "claude_code"
        assert coding_task.metadata["coding_mode"] == "repo_edit"

    def test_finance_task_in_same_mission_is_unaffected(self):
        # Test D (part 1): hints are coding-only, never leak to other departments.
        orchestrator = DepartmentOrchestrator()
        mission = Mission(
            title="fix it", description="fix it", departments=["coding", "finance"],
            execution_hints={"preferred_ai_provider": "claude_code", "coding_mode": "repo_edit"},
        )
        tasks = orchestrator.create_tasks(mission)

        finance_task = next(t for t in tasks if t.agent == "finance")
        assert "coding_mode" not in finance_task.metadata
        assert finance_task.metadata.get("preferred_ai_provider") != "claude_code"

    def test_no_hints_leaves_coding_task_unchanged(self):
        # Old Mission construction (no execution_hints) -- must be identical
        # to pre-fix behavior.
        orchestrator = DepartmentOrchestrator()
        mission = Mission(title="fix it", description="fix it", departments=["coding"])
        tasks = orchestrator.create_tasks(mission)

        coding_task = next(t for t in tasks if t.agent == "coding")
        assert "coding_mode" not in coding_task.metadata


class TestD_NonCodingMissionNeverGetsClaudeCodeHint:
    def test_finance_only_mission_ignores_hints_entirely(self):
        orchestrator = DepartmentOrchestrator()
        mission = Mission(
            title="analyze market", description="analyze market", departments=["finance"],
            execution_hints={"preferred_ai_provider": "claude_code", "coding_mode": "repo_edit"},
        )
        tasks = orchestrator.create_tasks(mission)

        assert all(t.agent != "coding" for t in tasks)
        finance_task = next(t for t in tasks if t.agent == "finance")
        assert finance_task.metadata.get("preferred_ai_provider") != "claude_code"
        assert "coding_mode" not in finance_task.metadata


class TestD2_UnknownProviderIsDroppedNotFailed:
    """Documented choice: an unknown/invalid preferred_ai_provider is
    DROPPED (falls back to normal automatic routing), matching the
    existing ProviderManager.route_and_generate(preferred_provider=...)
    precedent of silently falling back rather than erroring the request."""

    def test_unknown_provider_name_is_dropped(self, tmp_path):
        cleaned = _service(tmp_path)._validate_execution_hints({"preferred_ai_provider": "totally_fake_provider"})
        assert cleaned == {}

    def test_non_string_provider_is_dropped(self, tmp_path):
        cleaned = _service(tmp_path)._validate_execution_hints({"preferred_ai_provider": 12345})
        assert cleaned == {}


class TestE_UnknownCodingModeFailsClosed:
    """Documented choice: an unrecognized coding_mode is DROPPED, which
    means the task simply runs on the ordinary advisory (non-edit) path --
    the safe default. It can never grant edit capability for a value the
    system doesn't recognize."""

    def test_unknown_coding_mode_is_dropped(self, tmp_path):
        cleaned = _service(tmp_path)._validate_execution_hints({"coding_mode": "delete_everything"})
        assert cleaned == {}

    def test_dropped_coding_mode_never_reaches_task_metadata(self, tmp_path):
        cleaned = _service(tmp_path)._validate_execution_hints({"coding_mode": "not_a_real_mode"})
        orchestrator = DepartmentOrchestrator()
        mission = Mission(title="x", description="x", departments=["coding"], execution_hints=cleaned)
        tasks = orchestrator.create_tasks(mission)
        coding_task = next(t for t in tasks if t.agent == "coding")
        assert "coding_mode" not in coding_task.metadata


class TestF_ArbitraryClientFieldsCannotBeInjected:
    def test_only_allowlisted_keys_survive_validation(self, tmp_path):
        cleaned = _service(tmp_path)._validate_execution_hints({
            "preferred_ai_provider": "claude_code",
            "coding_mode": "repo_edit",
            "approved": True,
            "standing_permission": True,
            "shell_command": "rm -rf /",
            "repo_path": "C:/Windows",
            "arbitrary_field": "should never appear",
        })
        assert cleaned == {"preferred_ai_provider": "claude_code", "coding_mode": "repo_edit"}
        assert "approved" not in cleaned
        assert "shell_command" not in cleaned
        assert "repo_path" not in cleaned

    def test_non_dict_hints_are_ignored_entirely(self, tmp_path):
        assert _service(tmp_path)._validate_execution_hints("preferred_ai_provider=claude_code") == {}
        assert _service(tmp_path)._validate_execution_hints(["claude_code"]) == {}


class TestG_ExplicitSelectionStillGoesThroughProviderManager:
    """Explicit hint reaches task.metadata["preferred_ai_provider"], which
    CodingAgent already threads into ProviderManager.route_and_generate --
    no parallel path to the CLI is created here."""

    def test_hint_lands_in_the_same_metadata_key_coding_agent_already_reads(self):
        import inspect

        from src.agents.coding_agent import CodingAgent

        source = inspect.getsource(CodingAgent.execute)
        assert 'metadata.get("preferred_ai_provider")' in source

        orchestrator = DepartmentOrchestrator()
        mission = Mission(
            title="fix it", description="fix it", departments=["coding"],
            execution_hints={"preferred_ai_provider": "claude_code"},
        )
        tasks = orchestrator.create_tasks(mission)
        coding_task = next(t for t in tasks if t.agent == "coding")
        assert coding_task.metadata["preferred_ai_provider"] == "claude_code"


class TestH_UnrelatedAuthorityUnchanged:
    """Structural check: the fields this fix touches are unrelated to
    YouTube/finance/OAuth authority -- those modules are untouched."""

    def test_execution_hints_validation_has_no_finance_youtube_oauth_surface(self, tmp_path):
        import inspect

        source = inspect.getsource(ControlCenterService._validate_execution_hints)
        for forbidden in ("youtube", "finance", "oauth", "publish", "trade"):
            assert forbidden not in source.casefold()
