from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.capabilities.integration_lifecycle import (
    IntegrationLifecycleManager, classify_cuda, discover_runtime_interface,
    parse_requirements, python_constraint_compatibility,
)
from src.control_center.service import ControlCenterService
from src.control_center.store import ControlCenterStore
from src.capabilities.capability_installer import ControlledCapabilityInstaller
from src.sandbox.models import SandboxResult, SandboxStatus


class Runtime:
    state = "running"; BOOTING = "booting"; last_error = None
    def shutdown(self): pass


class Executor:
    def __init__(self, success=True): self.success, self.calls = success, []
    def verify(self, plan):
        self.calls.append(plan)
        return {"success": self.success, "runtime_interface": "python-module:autodub",
                "verified_dependencies": ["torch", "ffmpeg"], "security_findings": []}


class InstallerManager:
    def __init__(self, root): self.root = Path(root); self.cleaned = []
    def create(self, url):
        return SandboxResult("acme/tool", url, str(self.root), SandboxStatus.CREATED)
    def clone_repository(self, result):
        self.root.mkdir(); (self.root / "main.py").write_text("x = 1\n", encoding="utf-8")
        result.status = SandboxStatus.ANALYZING; return result
    def inspect(self, result): return result
    def detect_manifests(self, result): return result
    def scan_security(self, result): return result


def seeded(tmp_path, *, environment=None):
    store = ControlCenterStore(tmp_path / "state.json")
    evaluation_fp = "e" * 64
    tool = {"capability_id": "github-acme-tool", "repository": "acme/tool", "name": "tool",
            "status": "SANDBOX_VERIFIED", "discovery_state": "SANDBOX_VERIFIED", "available": False,
            "requires_approval": True, "evaluation_fingerprint": evaluation_fp,
            "source_evidence": {"files": {"requirements.txt": "torch>=2\n"},
                "metadata": {"requires_python": ">=3.11"}, "readme": "do not execute: powershell evil"}}
    evaluation = {"capability_id": "github-acme-tool", "repository": "acme/tool", "current": True,
                  "evaluation_fingerprint": evaluation_fp, "project_type": "EXECUTABLE_TOOL", "risk_level": "MEDIUM",
                  "runtime_requirements": {"python": "DECLARED", "ffmpeg": "REQUIRED", "cuda": "UNKNOWN"},
                  "network_requirements": "UNKNOWN", "requires_api_key": "UNKNOWN", "requires_account": "UNKNOWN"}
    sandbox = {"proposal_id": "sandbox-1", "id": "sandbox-1", "capability_id": "github-acme-tool",
               "repository": "acme/tool", "evaluation_fingerprint": evaluation_fp,
               "requested_action": "SANDBOX_VERIFICATION", "status": "SANDBOX_VERIFIED",
               "sandbox_result": {"success": True, "mode": "static_analysis", "status": "ready_for_review"}}
    store.update(lambda s: (s["autonomous_research"]["tools"].append(tool),
                            s["autonomous_research"]["evaluations"].append(evaluation),
                            s["autonomous_research"]["proposals"].append(sandbox)))
    env = environment or {"os": "TestOS", "python": "3.11.9", "ffmpeg": True, "git": True,
                          "cuda": "UNKNOWN", "gpu": "UNKNOWN", "free_disk_bytes": 1000, "ram_bytes": "UNKNOWN"}
    return store, IntegrationLifecycleManager(store), env


def approve(store, proposal):
    return ControlCenterService(Runtime(), store).decide_approval(proposal["approval_id"], True)


def plan_and_approve(tmp_path):
    store, manager, env = seeded(tmp_path); plan = manager.plan("github-acme-tool", env)
    proposal = next(x for x in store.snapshot()["autonomous_research"]["proposals"] if x.get("requested_action") == "CONTROLLED_INTEGRATION")
    approve(store, proposal); return store, manager, plan, proposal


def test_verified_creates_complete_idempotent_plan_and_proposal(tmp_path):
    store, manager, env = seeded(tmp_path)
    first = manager.plan("github-acme-tool", env); second = manager.plan("github-acme-tool", env)
    assert first["integration_plan_id"] == second["integration_plan_id"]
    assert first["compatibility"] == "PARTIAL" and first["required_runtime"]["python"] == ">=3.11"
    assert first["runtime_python_compatibility"] == "COMPATIBLE"
    assert first["dependency_python_compatibility"] == "UNKNOWN"
    assert next(x for x in first["required_system_dependencies"] if x["name"] == "ffmpeg")["verified"] is True
    assert first["manifest_analysis"]["trust_boundary"] == "UNTRUSTED_EXTERNAL_CONTENT"
    state = store.snapshot()["autonomous_research"]
    assert len(state["integration_plans"]) == 1
    assert len([x for x in state["proposals"] if x.get("requested_action") == "CONTROLLED_INTEGRATION"]) == 1
    assert state["capabilities"] == []


def test_not_sandbox_verified_has_no_plan(tmp_path):
    store, manager, env = seeded(tmp_path)
    store.update(lambda s: s["autonomous_research"]["tools"][0].update(status="SANDBOX_FAILED"))
    with pytest.raises(RuntimeError, match="SANDBOX_VERIFIED"): manager.plan("github-acme-tool", env)
    assert store.snapshot()["autonomous_research"]["integration_plans"] == []


def test_changed_environment_or_evaluation_changes_plan_and_supersedes(tmp_path):
    store, manager, env = seeded(tmp_path); first = manager.plan("github-acme-tool", env)
    second = manager.plan("github-acme-tool", {**env, "free_disk_bytes": 999})
    assert first["integration_plan_fingerprint"] != second["integration_plan_fingerprint"]
    assert store.snapshot()["autonomous_research"]["integration_plans"][0]["status"] == "SUPERSEDED"
    store.update(lambda s: (s["autonomous_research"]["evaluations"][0].update(evaluation_fingerprint="n" * 64),
                            s["autonomous_research"]["tools"][0].update(evaluation_fingerprint="n" * 64),
                            s["autonomous_research"]["proposals"][0].update(evaluation_fingerprint="n" * 64)))
    third = manager.plan("github-acme-tool", env)
    assert third["integration_plan_fingerprint"] != second["integration_plan_fingerprint"]


def test_requirements_are_data_and_risky_entries_flagged(monkeypatch):
    called = []
    monkeypatch.setattr("os.system", lambda *args: called.append(args))
    parsed = parse_requirements("safe_pkg>=1.2\nevil @ https://evil/x.whl\ngit+https://evil/repo\n-r more.txt\n$(touch pwned)\n")
    assert parsed["packages"][0]["name"] == "safe_pkg" and len(parsed["risky_entries"]) == 4 and called == []


def test_official_pytorch_cpu_index_is_narrowly_accepted_as_data():
    parsed = parse_requirements("torch==2.5.1+cpu\n--index-url https://download.pytorch.org/whl/cpu\n")
    assert parsed["risky_entries"] == []
    assert parsed["package_indexes"] == ["https://download.pytorch.org/whl/cpu"]


@pytest.mark.parametrize("line", [
    "--index-url http://download.pytorch.org/whl/cpu",
    "--index-url https://download.pytorch.org/whl/cu124",
    "--index-url https://user:pass@download.pytorch.org/whl/cpu",
    "--index-url https://download.pytorch.org:bad/whl/cpu",
    "--index-url https://download.pytorch.org/whl/cpu?x=1",
    "--extra-index-url https://download.pytorch.org/whl/cpu",
])
def test_untrusted_or_broadened_indexes_remain_blocked(line):
    parsed = parse_requirements(line + "\n")
    assert parsed["package_indexes"] == [] and parsed["risky_entries"][0]["reason"] == "DIRECTIVE"


def test_existing_approved_plan_shape_accepts_only_exact_legacy_pytorch_index():
    base = {"credentials_required": {}, "models/resources": "UNKNOWN", "proposed_runtime_interface": {"type": "PYTHON_FILE"}}
    legacy = {**base, "manifest_analysis": {"risky_entries": [
        {"line": 13, "value": "--index-url https://download.pytorch.org/whl/cpu", "reason": "DIRECTIVE"}]}}
    ControlledCapabilityInstaller._preflight(legacy)
    assert ControlledCapabilityInstaller._package_index_args(legacy) == [
        "--index-url", "https://download.pytorch.org/whl/cpu"]
    legacy["manifest_analysis"]["risky_entries"][0]["value"] = "--index-url https://evil.example/simple"
    with pytest.raises(RuntimeError, match="Risky dependency"):
        ControlledCapabilityInstaller._preflight(legacy)


def test_python_constraints_are_semantic_and_dependency_fit_stays_unknown(tmp_path):
    assert python_constraint_compatibility(">=3.11", "3.13.14")[0] == "COMPATIBLE"
    assert python_constraint_compatibility(">=3.9,<3.12", "3.13.14")[0] == "INCOMPATIBLE"
    assert python_constraint_compatibility(">=3.10.12", "3.10.9")[0] == "INCOMPATIBLE"
    store, manager, env = seeded(tmp_path, environment={"os": "TestOS", "python": "3.13.14", "ffmpeg": True,
        "git": True, "cuda": "UNKNOWN", "gpu": "UNKNOWN", "free_disk_bytes": 1000, "ram_bytes": "UNKNOWN"})
    plan = manager.plan("github-acme-tool", env)
    assert plan["runtime_python_compatibility"] == "COMPATIBLE"
    assert plan["dependency_python_compatibility"] == "UNKNOWN" and plan["compatibility"] == "PARTIAL"


@pytest.mark.parametrize(("claim", "classification", "required"), [
    ("CUDA required", "REQUIRED", True),
    ("CUDA is optional; runs on CPU", "OPTIONAL", False),
    ("CUDA recommended for acceleration", "RECOMMENDED", False),
    ("Supports CUDA builds", "UNKNOWN", "UNKNOWN"),
])
def test_cuda_claim_classification(claim, classification, required):
    result = classify_cuda({"readme": claim}, {"cuda": "REQUIRED"})
    assert result["classification"] == classification and result["required"] == required


def test_passive_runtime_interface_discovery_ignores_readme_commands(monkeypatch):
    calls = []
    monkeypatch.setattr("builtins.__import__", lambda *args, **kwargs: calls.append(args) or __import__(*args, **kwargs))
    main = "def main(): pass\nif __name__ == '__main__':\n    main()\n"
    interface = discover_runtime_interface({"files": {"main.py": main}, "readme": "python evil.py; powershell evil"})
    assert interface["type"] == "PYTHON_FILE" and interface["invocation_shape"] == "python main.py"
    assert discover_runtime_interface({"files": {"requirements.txt": "x"}, "readme": "python evil.py"}) == "UNKNOWN"
    assert calls == []


def test_claim_plus_structural_files_yields_all_verified_interfaces_without_authority():
    claims = [{"entry_path": "subtitle_generator.py", "evidence_identity": "readme"},
              {"entry_path": "manual_dubbing.py", "evidence_identity": "readme"}]
    result = discover_runtime_interface({"files": {"subtitle_generator.py": "x = 1", "manual_dubbing.py": "x = 2"}}, claims)
    assert result["status"] == "VERIFIED" and result["invocation_authority"] is False
    assert [row["entry_path"] for row in result["interfaces"]] == ["manual_dubbing.py", "subtitle_generator.py"]
    assert discover_runtime_interface({"files": {}}, claims) == "UNKNOWN"


def test_structured_evaluation_runtime_reaches_plan_and_changes_fingerprint(tmp_path):
    store, manager, env = seeded(tmp_path, environment={"os": "TestOS", "python": "3.13.14", "ffmpeg": True,
        "git": True, "cuda": "UNKNOWN", "gpu": "UNKNOWN", "free_disk_bytes": 1000, "ram_bytes": "UNKNOWN"})
    store.update(lambda s: (s["autonomous_research"]["tools"][0]["source_evidence"].update(
        files={"requirements.txt": "torch>=2\n", "subtitle_generator.py": "x = 1", "manual_dubbing.py": "x = 2"}, metadata={}),
        s["autonomous_research"]["evaluations"][0].update(
            runtime_requirements={"python": {"declared": True, "constraint": ">=3.11", "verification": "REPOSITORY_CLAIM"}, "ffmpeg": "REQUIRED", "cuda": "RECOMMENDED"},
            runtime_interface_claims=[{"entry_path": "subtitle_generator.py", "evidence_identity": "r"}, {"entry_path": "manual_dubbing.py", "evidence_identity": "r"}])))
    first = manager.plan("github-acme-tool", env)
    assert first["required_runtime"]["python"] == ">=3.11"
    assert first["runtime_python_compatibility"] == "COMPATIBLE"
    assert first["dependency_python_compatibility"] == "UNKNOWN" and first["compatibility"] == "PARTIAL"
    assert first["proposed_runtime_interface"]["status"] == "VERIFIED"
    assert [row["name"] for row in first["required_system_dependencies"]] == ["ffmpeg"]
    store.update(lambda s: s["autonomous_research"]["evaluations"][0]["runtime_interface_claims"].pop())
    second = manager.plan("github-acme-tool", env)
    assert first["integration_plan_fingerprint"] != second["integration_plan_fingerprint"]


def test_pyproject_console_script_is_structural_interface():
    interface = discover_runtime_interface({"files": {"pyproject.toml": '[project.scripts]\nautodub = "pkg.cli:main"\n'}})
    assert interface["type"] == "CONSOLE_SCRIPT" and interface["callable"] == "pkg.cli:main"


def test_material_change_supersedes_pending_without_approval_transfer(tmp_path):
    store, manager, env = seeded(tmp_path); first = manager.plan("github-acme-tool", env)
    old_proposal = next(x for x in store.snapshot()["autonomous_research"]["proposals"] if x.get("requested_action") == "CONTROLLED_INTEGRATION")
    old_approval = next(x for x in store.snapshot()["approvals"] if x["id"] == old_proposal["approval_id"])
    second = manager.plan("github-acme-tool", {**env, "python": "3.13.14"})
    state = store.snapshot(); new_proposals = [x for x in state["autonomous_research"]["proposals"] if x.get("requested_action") == "CONTROLLED_INTEGRATION"]
    assert first["integration_plan_fingerprint"] != second["integration_plan_fingerprint"]
    assert old_proposal["proposal_id"] != new_proposals[-1]["proposal_id"]
    assert next(x for x in state["approvals"] if x["id"] == old_approval["id"])["status"] == "SUPERSEDED"
    assert new_proposals[-1]["status"] == "PENDING"


@pytest.mark.parametrize("decision", [False, None])
def test_pending_rejected_and_wrong_sandbox_approval_never_execute(tmp_path, decision):
    store, manager, _plan, proposal = plan_and_approve(tmp_path); executor = Executor()
    store.update(lambda s: (s["approvals"][-1].update(status="REJECTED" if decision is False else "CHANGES_REQUESTED"),
                            next(x for x in s["autonomous_research"]["proposals"] if x.get("proposal_id") == proposal["proposal_id"]).update(status="REJECTED")))
    with pytest.raises(RuntimeError, match="Exact approved"): manager.execute_integration(proposal["proposal_id"], executor)
    assert executor.calls == []
    store.update(lambda s: (s["approvals"][-1].update(status="APPROVED"),
                            next(x for x in s["autonomous_research"]["proposals"] if x.get("proposal_id") == proposal["proposal_id"]).update(status="APPROVED_PENDING_EXECUTOR"),
                            s["approvals"][-1]["binding"].update(requested_action="SANDBOX_VERIFICATION")))
    with pytest.raises(RuntimeError, match="binding mismatch"): manager.execute_integration(proposal["proposal_id"], executor)
    assert executor.calls == []


def test_stale_fingerprint_repository_and_replay_fail_closed(tmp_path):
    store, manager, _plan, proposal = plan_and_approve(tmp_path); executor = Executor()
    store.update(lambda s: s["autonomous_research"]["tools"][0].update(repository="evil/repo"))
    with pytest.raises(RuntimeError, match="Repository"): manager.execute_integration(proposal["proposal_id"], executor)
    store.update(lambda s: s["autonomous_research"]["tools"][0].update(repository="acme/tool"))
    assert manager.execute_integration(proposal["proposal_id"], executor)["success"]
    with pytest.raises(RuntimeError, match="Exact approved"): manager.execute_integration(proposal["proposal_id"], executor)
    assert len(executor.calls) == 1


def test_stale_sandbox_result_never_executes(tmp_path):
    store, manager, _plan, proposal = plan_and_approve(tmp_path); executor = Executor()
    store.update(lambda s: s["autonomous_research"]["proposals"][0]["sandbox_result"].update(success=False))
    with pytest.raises(RuntimeError, match="Stale sandbox"):
        manager.execute_integration(proposal["proposal_id"], executor)
    assert executor.calls == []


def test_integration_failure_and_success_never_activate(tmp_path):
    store, manager, _plan, proposal = plan_and_approve(tmp_path)
    manager.execute_integration(proposal["proposal_id"], Executor(False))
    state = store.snapshot()["autonomous_research"]
    assert state["tools"][0]["status"] == "INTEGRATION_FAILED" and state["capabilities"] == []


def test_retry_after_integration_failure_creates_fresh_exact_bound_proposal_and_recovers(tmp_path):
    store, manager, env = seeded(tmp_path)
    manager.plan("github-acme-tool", env)
    failed_proposal = next(x for x in store.snapshot()["autonomous_research"]["proposals"] if x.get("requested_action") == "CONTROLLED_INTEGRATION")
    approve(store, failed_proposal)
    manager.execute_integration(failed_proposal["proposal_id"], Executor(False))
    state = store.snapshot()["autonomous_research"]
    assert state["tools"][0]["status"] == "INTEGRATION_FAILED"
    assert state["integration_plans"][0]["status"] == "INTEGRATION_FAILED"

    # Root cause fixed elsewhere (e.g. requirements.txt parsing); sandbox evidence and
    # evaluation are unchanged, so the re-plan reproduces the exact same plan fingerprint.
    retried_plan = manager.plan("github-acme-tool", env)
    assert retried_plan["integration_plan_id"] == failed_proposal["integration_plan_id"]
    assert retried_plan["evaluation_fingerprint"] == failed_proposal["evaluation_fingerprint"]
    assert retried_plan["sandbox_verification_identity"] == failed_proposal["sandbox_verification_identity"]

    state = store.snapshot()["autonomous_research"]
    controlled = [x for x in state["proposals"] if x.get("requested_action") == "CONTROLLED_INTEGRATION"]
    assert len(controlled) == 2
    retry_proposal = controlled[-1]
    assert retry_proposal["proposal_id"] != failed_proposal["proposal_id"]
    assert retry_proposal["status"] == "PENDING"
    assert retry_proposal["evaluation_fingerprint"] == failed_proposal["evaluation_fingerprint"]
    assert retry_proposal["sandbox_verification_identity"] == failed_proposal["sandbox_verification_identity"]
    assert state["tools"][0]["status"] == "INTEGRATION_APPROVAL_REQUIRED"

    # Old failed proposal/approval stay terminal; never silently resurrected.
    stale_proposal = next(x for x in state["proposals"] if x["proposal_id"] == failed_proposal["proposal_id"])
    assert stale_proposal["status"] == "INTEGRATION_FAILED"
    stale_approval = next(x for x in store.snapshot()["approvals"] if x["id"] == failed_proposal["approval_id"])
    assert stale_approval["status"] == "APPROVED"
    with pytest.raises(RuntimeError, match="Exact approved"):
        manager.execute_integration(failed_proposal["proposal_id"], Executor(True))

    # Re-planning again before approval is idempotent: no duplicate proposal spawned.
    manager.plan("github-acme-tool", env)
    state = store.snapshot()["autonomous_research"]
    assert len([x for x in state["proposals"] if x.get("requested_action") == "CONTROLLED_INTEGRATION"]) == 2

    approve(store, retry_proposal)
    outcome = manager.execute_integration(retry_proposal["proposal_id"], Executor(True))
    assert outcome["success"] is True
    state = store.snapshot()["autonomous_research"]
    assert state["tools"][0]["status"] == "INTEGRATION_VERIFIED"
    assert state["capabilities"] == []


def test_retry_denied_when_evaluation_fingerprint_stale(tmp_path):
    store, manager, env = seeded(tmp_path)
    manager.plan("github-acme-tool", env)
    proposal = next(x for x in store.snapshot()["autonomous_research"]["proposals"] if x.get("requested_action") == "CONTROLLED_INTEGRATION")
    approve(store, proposal)
    manager.execute_integration(proposal["proposal_id"], Executor(False))
    # Evaluation was re-run (new fingerprint) but the tool's bound fingerprint was not resynced.
    store.update(lambda s: s["autonomous_research"]["evaluations"][0].update(evaluation_fingerprint="f" * 64))
    with pytest.raises(RuntimeError, match="Current evaluation binding mismatch"):
        manager.plan("github-acme-tool", env)


def test_retry_denied_when_sandbox_verification_superseded(tmp_path):
    store, manager, env = seeded(tmp_path)
    manager.plan("github-acme-tool", env)
    proposal = next(x for x in store.snapshot()["autonomous_research"]["proposals"] if x.get("requested_action") == "CONTROLLED_INTEGRATION")
    approve(store, proposal)
    manager.execute_integration(proposal["proposal_id"], Executor(False))
    store.update(lambda s: s["autonomous_research"]["proposals"][0].update(status="SUPERSEDED"))
    with pytest.raises(RuntimeError, match="Current sandbox verification required"):
        manager.plan("github-acme-tool", env)


def test_retry_denied_on_repository_mismatch(tmp_path):
    store, manager, env = seeded(tmp_path)
    manager.plan("github-acme-tool", env)
    proposal = next(x for x in store.snapshot()["autonomous_research"]["proposals"] if x.get("requested_action") == "CONTROLLED_INTEGRATION")
    approve(store, proposal)
    manager.execute_integration(proposal["proposal_id"], Executor(False))
    store.update(lambda s: s["autonomous_research"]["tools"][0].update(repository="evil/repo"))
    with pytest.raises(RuntimeError, match="repository mismatch"):
        manager.plan("github-acme-tool", env)


def integrated(tmp_path):
    store, manager, plan, proposal = plan_and_approve(tmp_path); manager.execute_integration(proposal["proposal_id"], Executor())
    return store, manager, plan


def test_activation_requires_separate_exact_approval_and_is_idempotent(tmp_path):
    store, manager, _ = integrated(tmp_path); proposal = manager.propose_activation("github-acme-tool")
    with pytest.raises(RuntimeError, match="Exact approved"): manager.activate(proposal["proposal_id"])
    # An integration approval cannot authorize activation.
    integration_approval = next(x for x in store.snapshot()["approvals"] if x["binding"]["requested_action"] == "CONTROLLED_INTEGRATION")
    store.update(lambda s: next(x for x in s["autonomous_research"]["proposals"] if x["proposal_id"] == proposal["proposal_id"]).update(
        approval_id=integration_approval["id"], status="APPROVED_PENDING_EXECUTOR"))
    with pytest.raises(RuntimeError, match="binding mismatch"): manager.activate(proposal["proposal_id"])
    store.update(lambda s: next(x for x in s["autonomous_research"]["proposals"] if x["proposal_id"] == proposal["proposal_id"]).update(approval_id="approval-" + proposal["proposal_id"]))
    approve(store, proposal); row = manager.activate(proposal["proposal_id"])
    assert row["status"] == "ACTIVE_CAPABILITY" and row["integration_fingerprint"]
    assert manager.activate(proposal["proposal_id"])["capability_id"] == row["capability_id"]
    assert len(store.snapshot()["autonomous_research"]["capabilities"]) == 1


@pytest.mark.parametrize("mutation,error", [
    (lambda s: s["autonomous_research"]["integration_plans"][0].update(proposed_runtime_interface="UNKNOWN"), "Runtime interface"),
    (lambda s: s["autonomous_research"]["integration_plans"][0]["required_dependencies"][0].update(verified="UNKNOWN"), "dependency"),
    (lambda s: s["autonomous_research"]["integration_verifications"][0]["result"].update(security_findings=[{"severity": "HIGH", "resolved": False}]), "security"),
])
def test_activation_policy_fail_closed(tmp_path, mutation, error):
    store, manager, _ = integrated(tmp_path); mutation(store.snapshot())
    store.update(mutation)
    with pytest.raises(RuntimeError, match=error): manager.propose_activation("github-acme-tool")
    assert store.snapshot()["autonomous_research"]["capabilities"] == []


def test_no_commands_urls_or_secrets_are_passed_to_executor(tmp_path):
    store, manager, _plan, proposal = plan_and_approve(tmp_path); executor = Executor()
    manager.execute_integration(proposal["proposal_id"], executor)
    payload = json.dumps(executor.calls[0]).casefold()
    assert "powershell evil" not in payload and "secret-value" not in payload


def test_production_service_wires_controlled_installer(tmp_path):
    service = ControlCenterService(Runtime(), ControlCenterStore(tmp_path / "state.json"))
    assert isinstance(service.controlled_integration_executor, ControlledCapabilityInstaller)


def test_controlled_installer_uses_isolated_python_and_scrubs_credentials(tmp_path, monkeypatch):
    manager = InstallerManager(tmp_path / "sandbox")
    calls = []
    def build(environment):
        python = Path(environment) / ("Scripts/python.exe" if __import__("os").name == "nt" else "bin/python")
        python.parent.mkdir(parents=True); python.touch()
    monkeypatch.setattr("src.capabilities.capability_installer.venv.EnvBuilder.create", lambda _self, path: build(path))
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-leak")
    def runner(command, **kwargs):
        calls.append((command, kwargs)); return SimpleNamespace(returncode=0, stdout="", stderr="")
    plan = {"repository": "acme/tool", "required_dependencies": [{"name": "safe", "extras": "", "constraint": "==1.0", "marker": "UNKNOWN"}],
            "required_system_dependencies": [], "manifest_analysis": {"risky_entries": []},
            "credentials_required": {"api_key": False}, "models/resources": "UNKNOWN",
            "proposed_runtime_interface": {"type": "PYTHON_FILE", "entry_path": "main.py"}}
    outcome = ControlledCapabilityInstaller(manager, runner).verify(plan)
    assert outcome["success"] is True and calls
    assert all("AWS_SECRET_ACCESS_KEY" not in call[1]["env"] for call in calls)
    assert all(str(tmp_path / "sandbox" / ".jarvis-venv") in call[0][0] for call in calls)


def test_controlled_installer_stops_for_model_and_rolls_back_failure(tmp_path, monkeypatch):
    manager = InstallerManager(tmp_path / "sandbox")
    removed = []
    monkeypatch.setattr("src.capabilities.capability_installer.safe_rmtree", lambda path: removed.append(path) or True)
    plan = {"repository": "acme/tool", "required_dependencies": [], "manifest_analysis": {"risky_entries": []},
            "credentials_required": {}, "models/resources": ["large-model"],
            "proposed_runtime_interface": {"type": "PYTHON_FILE", "entry_path": "main.py"}}
    assert ControlledCapabilityInstaller(manager).verify(plan)["error"] == "Model/resource download requires separate approval"
    plan["models/resources"] = "UNKNOWN"
    monkeypatch.setattr("src.capabilities.capability_installer.venv.EnvBuilder.create", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    outcome = ControlledCapabilityInstaller(manager).verify(plan)
    assert outcome["success"] is False and outcome["rolled_back"] is True
    assert removed == [str(tmp_path / "sandbox")]
