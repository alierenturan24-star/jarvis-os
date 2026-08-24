from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tomllib
from urllib.parse import urlsplit
from datetime import datetime, timezone
from typing import Any, Protocol

UNKNOWN = "UNKNOWN"

_TRUSTED_PACKAGE_INDEXES = {"https://download.pytorch.org/whl/cpu"}


def trusted_package_index(line: str) -> str | None:
    """Return a narrowly allowlisted package index without resolving or contacting it."""
    match = re.fullmatch(r"--index-url(?:\s+|=)(\S+)", line.strip(), re.I)
    if not match:
        return None
    url = match.group(1).rstrip("/")
    try:
        parsed = urlsplit(url)
        has_authority_override = parsed.username is not None or parsed.password is not None or parsed.port is not None
    except ValueError:
        return None
    if (has_authority_override or parsed.query or parsed.fragment):
        return None
    return url if url in _TRUSTED_PACKAGE_INDEXES else None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def local_environment_probe() -> dict[str, Any]:
    """Read-only local inventory. It never launches a command or imports a dependency."""
    result: dict[str, Any] = {
        "os": platform.system() or UNKNOWN,
        "python": platform.python_version() or UNKNOWN,
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "git": bool(shutil.which("git")),
        "cuda": UNKNOWN,
        "gpu": UNKNOWN,
        "free_disk_bytes": UNKNOWN,
        "ram_bytes": UNKNOWN,
    }
    try:
        result["free_disk_bytes"] = shutil.disk_usage(os.getcwd()).free
    except OSError:
        pass
    try:
        if hasattr(os, "sysconf"):
            result["ram_bytes"] = int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (OSError, ValueError, TypeError):
        pass
    return result


def parse_requirements(content: str) -> dict[str, Any]:
    """Parse requirement lines as untrusted text; no setup/import/install behavior exists here."""
    packages, risky, package_indexes = [], [], []
    for number, raw in enumerate(content.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        index = trusted_package_index(line)
        if index:
            package_indexes.append(index)
            continue
        if line.startswith(("-r", "--requirement", "-c", "--constraint", "--index-url", "--extra-index-url")):
            risky.append({"line": number, "value": line, "reason": "DIRECTIVE"})
            continue
        if re.search(r"(?:https?|git\+|svn\+|hg\+|bzr\+|file):", line, re.I) or " @ " in line:
            risky.append({"line": number, "value": line, "reason": "URL_OR_VCS"})
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_.-]*)(\[[A-Za-z0-9_,.-]+\])?\s*([^;]*?)(?:\s*;\s*(.+))?", line)
        if not match:
            risky.append({"line": number, "value": line, "reason": "UNPARSED"})
            continue
        packages.append({"name": match.group(1), "extras": match.group(2) or "", "constraint": match.group(3).strip() or UNKNOWN,
                         "marker": match.group(4) or UNKNOWN})
    return {"trust_boundary": "UNTRUSTED_EXTERNAL_CONTENT", "packages": packages,
            "package_indexes": package_indexes, "risky_entries": risky}


def _version(value: str) -> tuple[int, ...] | None:
    match = re.fullmatch(r"\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?\s*", str(value))
    return tuple(int(x or 0) for x in match.groups()) if match else None


def python_constraint_compatibility(requirement: str, current: str) -> tuple[str, str]:
    """Evaluate ordinary PEP 440 comparison clauses without package metadata execution."""
    actual = _version(current)
    if not actual or not isinstance(requirement, str) or requirement in {"", UNKNOWN, "DECLARED"}:
        return UNKNOWN, "Python version compatibility cannot be proven"
    clauses = [x.strip() for x in requirement.split(",") if x.strip()]
    if not clauses:
        return UNKNOWN, "Python version compatibility cannot be proven"
    for clause in clauses:
        match = re.fullmatch(r"(===|==|!=|>=|<=|>|<|~=)\s*(\d+(?:\.\d+){0,2})(?:\.\*)?", clause)
        if not match:
            return UNKNOWN, "Python version compatibility cannot be proven"
        op, expected_text = match.groups(); expected = _version(expected_text)
        assert expected is not None
        if op == "~=":
            compatible = actual >= expected and actual[:max(1, len(expected_text.split(".")) - 1)] == expected[:max(1, len(expected_text.split(".")) - 1)]
        else:
            compatible = {"==": actual == expected, "===": actual == expected, "!=": actual != expected,
                          ">=": actual >= expected, "<=": actual <= expected, ">": actual > expected, "<": actual < expected}[op]
        if not compatible:
            return "INCOMPATIBLE", f"Python {current} does not satisfy {requirement}"
    return "COMPATIBLE", f"Python {current} satisfies {requirement}"


def discover_runtime_interface(source: dict[str, Any], claims: list[dict[str, Any]] | None = None) -> dict[str, Any] | str:
    """Inspect persisted text only. Returned invocation shapes are constructed, never README commands."""
    files = source.get("files") if isinstance(source.get("files"), dict) else {}
    normalized = {str(path).replace("\\", "/").lstrip("./"): str(body) for path, body in files.items()}
    verified = []
    for claim in claims or []:
        path = str(claim.get("entry_path", ""))
        if path in normalized:
            verified.append({"type": "PYTHON_SCRIPT", "entry_path": path,
                             "role": ({"subtitle_generator.py": "subtitle_generation",
                                       "manual_dubbing.py": "dubbing"}.get(path, UNKNOWN)),
                             "evidence_identity": _fingerprint({"claim": claim.get("evidence_identity"), "path": path,
                                                                 "content": normalized[path]}),
                             "confidence": "HIGH", "verification": "STRUCTURALLY_PROVEN"})
    if verified:
        return {"status": "VERIFIED", "interfaces": sorted(verified, key=lambda row: row["entry_path"]),
                "invocation_authority": False}
    for path in sorted(normalized):
        if path.endswith("/__main__.py"):
            module = path[:-12].replace("/", ".")
            return {"type": "PYTHON_MODULE", "entry_path": path, "invocation_shape": f"python -m {module}".strip(),
                    "evidence_identity": _fingerprint({"path": path, "content": normalized[path]}), "confidence": "HIGH", "verification": "STRUCTURALLY_PROVEN"}
    pyproject = normalized.get("pyproject.toml")
    if pyproject:
        try:
            data = tomllib.loads(pyproject); scripts = data.get("project", {}).get("scripts", {})
            if isinstance(scripts, dict) and scripts:
                name, target = sorted((str(k), str(v)) for k, v in scripts.items())[0]
                if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", target):
                    return {"type": "CONSOLE_SCRIPT", "entry_path": "pyproject.toml", "invocation_shape": name,
                            "callable": target, "evidence_identity": _fingerprint({"path": "pyproject.toml", "target": target}),
                            "confidence": "HIGH", "verification": "STRUCTURALLY_PROVEN"}
        except (tomllib.TOMLDecodeError, AttributeError, TypeError):
            pass
    for path in ("__main__.py", "main.py", "app.py", "cli.py"):
        body = normalized.get(path)
        if body is not None and re.search(r"if\s+__name__\s*==\s*['\"]__main__['\"]\s*:", body):
            return {"type": "PYTHON_FILE", "entry_path": path, "invocation_shape": f"python {path}",
                    "evidence_identity": _fingerprint({"path": path, "content": body}), "confidence": "HIGH", "verification": "STRUCTURALLY_PROVEN"}
    return UNKNOWN


def classify_cuda(source: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    text = str(source.get("readme", "")).casefold()
    required = ("cuda required", "requires cuda", "cuda is required", "must have cuda", "cuda-only")
    optional = ("cuda optional", "optional cuda", "cuda is optional", "cpu fallback", "runs on cpu", "cpu-only mode")
    recommended = ("cuda recommended", "cuda is recommended", "gpu recommended", "recommended gpu", "for acceleration", "faster with cuda")
    if any(x in text for x in required): return {"classification": "REQUIRED", "required": True, "basis": "EXPLICIT_REQUIRED_CLAIM"}
    if any(x in text for x in optional): return {"classification": "OPTIONAL", "required": False, "basis": "OPTIONAL_OR_CPU_FALLBACK_CLAIM"}
    if any(x in text for x in recommended): return {"classification": "RECOMMENDED", "required": False, "basis": "ACCELERATION_RECOMMENDATION"}
    detail = runtime.get("cuda_evidence") if isinstance(runtime.get("cuda_evidence"), dict) else {}
    if detail.get("basis") == "EXPLICIT_REQUIRED_CLAIM" and runtime.get("cuda") == "REQUIRED":
        return {"classification": "REQUIRED", "required": True, "basis": "PERSISTED_EXPLICIT_REQUIRED_CLAIM"}
    return {"classification": UNKNOWN, "required": UNKNOWN, "basis": "AMBIGUOUS_OR_NO_EXPLICIT_CLAIM"}


class ControlledIntegrationExecutor(Protocol):
    def verify(self, plan: dict[str, Any]) -> dict[str, Any]: ...


class IntegrationLifecycleManager:
    def __init__(self, store: Any) -> None:
        self.store = store

    def plan(self, capability_id: str, environment: dict[str, Any] | None = None) -> dict[str, Any]:
        state = self.store.snapshot(); ar = state["autonomous_research"]
        tool = next((x for x in ar["tools"] if x.get("capability_id") == capability_id), None)
        if not tool: raise KeyError("Capability candidate not found")
        if tool.get("status") not in {"SANDBOX_VERIFIED", "INTEGRATION_APPROVAL_REQUIRED", "INTEGRATION_FAILED"}:
            raise RuntimeError("SANDBOX_VERIFIED required")
        evaluation = next((x for x in ar["evaluations"] if x.get("capability_id") == capability_id and x.get("current") is True), None)
        if not evaluation or evaluation.get("evaluation_fingerprint") != tool.get("evaluation_fingerprint"):
            raise RuntimeError("Current evaluation binding mismatch")
        sandbox_proposal = next((x for x in reversed(ar["proposals"]) if x.get("capability_id") == capability_id
                                 and x.get("requested_action") == "SANDBOX_VERIFICATION" and x.get("status") == "SANDBOX_VERIFIED"), None)
        if not sandbox_proposal: raise RuntimeError("Current sandbox verification required")
        if sandbox_proposal.get("evaluation_fingerprint") != evaluation["evaluation_fingerprint"] or self._repo(tool) != self._repo(sandbox_proposal):
            raise RuntimeError("Stale sandbox result or repository mismatch")
        sandbox_identity = _fingerprint({"proposal_id": sandbox_proposal["proposal_id"],
                                         "evaluation_fingerprint": evaluation["evaluation_fingerprint"],
                                         "result": sandbox_proposal.get("sandbox_result", {})})
        env = dict(environment or local_environment_probe())
        source = tool.get("source_evidence") if isinstance(tool.get("source_evidence"), dict) else {}
        files = source.get("files") if isinstance(source.get("files"), dict) else {}
        requirements = parse_requirements(str(files.get("requirements.txt", ""))) if "requirements.txt" in files else {
            "trust_boundary": "UNTRUSTED_EXTERNAL_CONTENT", "packages": [], "risky_entries": []}
        runtime = evaluation.get("runtime_requirements") or {}
        required_python = self._python_requirement(source, runtime)
        runtime_compatibility, runtime_reason = python_constraint_compatibility(required_python, str(env.get("python", UNKNOWN)))
        dependency_compatibility, dependency_reasons = self._dependency_python_compatibility(requirements, env)
        compatibility = ("INCOMPATIBLE" if "INCOMPATIBLE" in {runtime_compatibility, dependency_compatibility}
                         else "COMPATIBLE" if {runtime_compatibility, dependency_compatibility} == {"COMPATIBLE"}
                         else "PARTIAL" if runtime_compatibility == "COMPATIBLE" else UNKNOWN)
        reasons = [runtime_reason, *dependency_reasons]
        system = []
        if runtime.get("ffmpeg") == "REQUIRED": system.append({"name": "ffmpeg", "required": True, "verified": env.get("ffmpeg", UNKNOWN)})
        cuda = classify_cuda(source, runtime)
        if cuda["required"] is True:
            system.append({"name": "cuda", "required": cuda["required"], "recommendation": cuda["classification"],
                           "verified": env.get("cuda", UNKNOWN), "evidence_basis": cuda["basis"]})
        interface = discover_runtime_interface(source, evaluation.get("runtime_interface_claims", []))
        stable = {
            "capability_id": capability_id, "repository": tool.get("repository"),
            "evaluation_fingerprint": evaluation["evaluation_fingerprint"], "sandbox_verification_identity": sandbox_identity,
            "project_type": evaluation.get("project_type", UNKNOWN), "required_runtime": {"python": required_python},
            "required_dependencies": requirements["packages"], "required_system_dependencies": system,
            "optional_dependencies": self._optional_dependencies(source), "models/resources": UNKNOWN,
            "network_requirements": evaluation.get("network_requirements", UNKNOWN),
            "credentials_required": {"api_key": evaluation.get("requires_api_key", UNKNOWN), "account": evaluation.get("requires_account", UNKNOWN)},
            "detected_local_environment": env, "compatibility": compatibility, "compatibility_reasons": reasons,
            "runtime_python_compatibility": runtime_compatibility, "dependency_python_compatibility": dependency_compatibility,
            "proposed_installation_steps": ["Create isolated capability environment", "Install exact persisted manifest dependencies"],
            "proposed_verification_steps": ["Verify required dependency presence", "Verify runtime interface in isolation", "Record security findings"],
            "proposed_runtime_interface": interface, "filesystem_changes": ["isolated capability environment"],
            "environment_changes": ["isolated dependency environment"], "network_side_effects": ["dependency downloads"],
            "estimated_downloads": UNKNOWN, "estimated_disk_usage": UNKNOWN,
            "rollback_plan": ["Disable capability", "Remove isolated capability environment", "Restore registry metadata snapshot"],
            "risk": self._risk(requirements, evaluation, compatibility, interface, system),
            "manifest_analysis": requirements, "status": "INTEGRATION_APPROVAL_REQUIRED",
        }
        fingerprint = _fingerprint(stable); plan_id = "integration-plan-" + fingerprint[:24]
        plan = {"integration_plan_id": plan_id, **stable, "integration_plan_fingerprint": fingerprint, "created_at": utc_now()}
        self._persist_plan(plan)
        return next(x for x in self.store.snapshot()["autonomous_research"]["integration_plans"] if x["integration_plan_id"] == plan_id)

    def _persist_plan(self, plan: dict[str, Any]) -> None:
        def mutate(state: dict[str, Any]) -> None:
            ar = state["autonomous_research"]
            tool = next(x for x in ar["tools"] if x.get("capability_id") == plan["capability_id"])
            # A prior CONTROLLED_INTEGRATION attempt failed; this exact-bound re-plan is the sole
            # sanctioned recovery path, so an identical plan fingerprint must still yield a fresh
            # proposal/approval instead of silently no-oping or resurrecting the failed proposal.
            retry_after_failure = tool.get("status") == "INTEGRATION_FAILED"
            existing = next((x for x in ar["integration_plans"] if x.get("integration_plan_id") == plan["integration_plan_id"]), None)
            if existing and not retry_after_failure: return
            if not existing or not existing.get("current"):
                for old in ar["integration_plans"]:
                    if old.get("capability_id") == plan["capability_id"] and old.get("current"):
                        old["current"] = False; old["status"] = "SUPERSEDED"
                for proposal in ar["proposals"]:
                    if proposal.get("capability_id") == plan["capability_id"] and proposal.get("requested_action") == "CONTROLLED_INTEGRATION" and proposal.get("status") in {"PENDING", "APPROVED_PENDING_EXECUTOR"}:
                        proposal["status"] = "SUPERSEDED"
                        approval = next((a for a in state["approvals"] if a.get("id") == proposal.get("approval_id")), None)
                        if approval and approval.get("status") in {"PENDING", "APPROVED"}: approval["status"] = "SUPERSEDED"
            if existing:
                existing.update(current=True, status="INTEGRATION_APPROVAL_REQUIRED")
                active = existing
            else:
                plan["current"] = True; ar["integration_plans"].append(plan)
                active = plan
            prior_attempts = sum(1 for p in ar["proposals"] if p.get("integration_plan_id") == active["integration_plan_id"] and p.get("requested_action") == "CONTROLLED_INTEGRATION")
            proposal_id = "integration-proposal-" + _fingerprint({"integration_plan_fingerprint": active["integration_plan_fingerprint"], "attempt": prior_attempts})[:24]
            approval_id = "approval-" + proposal_id
            proposal = {"proposal_id": proposal_id, "id": proposal_id, "approval_id": approval_id,
                        "integration_plan_id": active["integration_plan_id"], "integration_plan_fingerprint": active["integration_plan_fingerprint"],
                        "capability_id": active["capability_id"], "repository": active["repository"],
                        "evaluation_fingerprint": active["evaluation_fingerprint"], "sandbox_verification_identity": active["sandbox_verification_identity"],
                        "requested_action": "CONTROLLED_INTEGRATION", "status": "PENDING", "created_at": utc_now()}
            ar["proposals"].append(proposal)
            binding = {key: proposal[key] for key in ("proposal_id", "integration_plan_id", "integration_plan_fingerprint", "capability_id",
                       "evaluation_fingerprint", "sandbox_verification_identity", "requested_action")}
            state["approvals"].append({"id": approval_id, "type": "capability_proposal", "status": "PENDING",
                "what": f"Controlled integration: {active['capability_id']}", "why": "Persisted integration plan requires side effects",
                "risk": active["risk"], "cost": UNKNOWN, "expected_result": "INTEGRATION_VERIFIED_OR_FAILED", "binding": binding,
                "details": {"integration_plan_id": active["integration_plan_id"]}, "created_at": utc_now()})
            tool.update(status="INTEGRATION_APPROVAL_REQUIRED", discovery_state="INTEGRATION_APPROVAL_REQUIRED", requires_approval=True, available=False)
            self._audit_state(ar, active["capability_id"], "INTEGRATION_PLANNED", {"integration_plan_id": active["integration_plan_id"]})
            self._audit_state(ar, active["capability_id"], "INTEGRATION_APPROVAL_REQUIRED", {"proposal_id": proposal_id})
        self.store.update(mutate)

    def execute_integration(self, proposal_id: str, executor: ControlledIntegrationExecutor) -> dict[str, Any]:
        state = self.store.snapshot(); ar = state["autonomous_research"]
        proposal = next((x for x in ar["proposals"] if x.get("proposal_id") == proposal_id), None)
        if not proposal: raise KeyError("Integration proposal not found")
        plan, approval, tool, evaluation = self._bound(proposal, "CONTROLLED_INTEGRATION", state)
        outcome = executor.verify(plan)
        success = bool(outcome.get("success"))
        safe = self._safe(outcome)
        def mutate(current: dict[str, Any]) -> None:
            car = current["autonomous_research"]
            p = next(x for x in car["proposals"] if x.get("proposal_id") == proposal_id)
            p["status"] = "INTEGRATION_VERIFIED" if success else "INTEGRATION_FAILED"; p["execution_claimed_at"] = utc_now()
            cp = next(x for x in car["integration_plans"] if x.get("integration_plan_id") == plan["integration_plan_id"])
            cp["status"] = p["status"]
            if success:
                verified_names = set(safe.get("verified_dependencies", []))
                for dep in cp.get("required_dependencies", []) + cp.get("required_system_dependencies", []):
                    dep["verified"] = dep.get("name") in verified_names
                if isinstance(safe.get("runtime_interface"), str) and safe["runtime_interface"].strip():
                    cp["proposed_runtime_interface"] = safe["runtime_interface"].strip()
            verification = {"integration_plan_id": cp["integration_plan_id"], "integration_plan_fingerprint": cp["integration_plan_fingerprint"],
                            "capability_id": cp["capability_id"], "success": success, "result": safe, "verified_at": utc_now()}
            car["integration_verifications"].append(verification)
            target = next(x for x in car["tools"] if x.get("capability_id") == cp["capability_id"])
            target.update(status=p["status"], discovery_state=p["status"], available=False, requires_approval=success)
            self._audit_state(car, cp["capability_id"], p["status"], {"integration_plan_id": cp["integration_plan_id"], "success": success})
        self.store.update(mutate)
        return safe

    def propose_activation(self, capability_id: str) -> dict[str, Any]:
        state = self.store.snapshot(); plan = self._activation_preflight(capability_id, state, require_approval=False)
        ar = state["autonomous_research"]
        proposal_id = "activation-proposal-" + _fingerprint({"capability_id": capability_id, "evaluation": plan["evaluation_fingerprint"],
                                                               "integration": plan["integration_plan_fingerprint"]})[:24]
        existing = next((x for x in ar["proposals"] if x.get("proposal_id") == proposal_id), None)
        if existing: return existing
        approval_id = "approval-" + proposal_id
        proposal = {"proposal_id": proposal_id, "id": proposal_id, "approval_id": approval_id, "capability_id": capability_id,
                    "repository": plan["repository"], "evaluation_fingerprint": plan["evaluation_fingerprint"],
                    "integration_plan_id": plan["integration_plan_id"], "integration_plan_fingerprint": plan["integration_plan_fingerprint"],
                    "sandbox_verification_identity": plan["sandbox_verification_identity"], "requested_action": "ACTIVATE_CAPABILITY",
                    "status": "PENDING", "created_at": utc_now()}
        binding = {key: proposal[key] for key in ("proposal_id", "integration_plan_id", "integration_plan_fingerprint", "capability_id",
                   "evaluation_fingerprint", "sandbox_verification_identity", "requested_action")}
        def mutate(current: dict[str, Any]) -> None:
            current["autonomous_research"]["proposals"].append(proposal)
            current["approvals"].append({"id": approval_id, "type": "capability_proposal", "status": "PENDING",
                "what": f"Activate capability: {capability_id}", "why": "Activation requires an independent exact-bound approval",
                "risk": plan["risk"], "cost": 0, "expected_result": "ACTIVE_CAPABILITY", "binding": binding,
                "details": {"integration_plan_id": plan["integration_plan_id"]}, "created_at": utc_now()})
            tool = next(x for x in current["autonomous_research"]["tools"] if x.get("capability_id") == capability_id)
            tool.update(status="ACTIVATION_APPROVAL_REQUIRED", discovery_state="ACTIVATION_APPROVAL_REQUIRED", available=False, requires_approval=True)
            self._audit_state(current["autonomous_research"], capability_id, "ACTIVATION_APPROVAL_REQUIRED", {"proposal_id": proposal_id})
        self.store.update(mutate); return proposal

    def activate(self, proposal_id: str) -> dict[str, Any]:
        state = self.store.snapshot(); ar = state["autonomous_research"]
        proposal = next((x for x in ar["proposals"] if x.get("proposal_id") == proposal_id), None)
        if not proposal: raise KeyError("Activation proposal not found")
        already = next((x for x in ar["capabilities"] if x.get("capability_id") == proposal.get("capability_id")
                        and x.get("activation_approval_identity") == proposal.get("approval_id")
                        and x.get("status") == "ACTIVE_CAPABILITY"), None)
        if proposal.get("status") == "ACTIVATED" and already:
            return already
        plan, _approval, tool, _evaluation = self._bound(proposal, "ACTIVATE_CAPABILITY", state)
        self._activation_preflight(proposal["capability_id"], state, require_approval=True)
        existing = next((x for x in ar["capabilities"] if x.get("capability_id") == proposal["capability_id"]), None)
        if existing and existing.get("status") == "ACTIVE_CAPABILITY": return existing
        now = utc_now(); row = {"capability_id": proposal["capability_id"], "repository": plan["repository"],
            "version/revision_identity": UNKNOWN, "evaluation_fingerprint": plan["evaluation_fingerprint"],
            "integration_fingerprint": plan["integration_plan_fingerprint"], "activation_approval_identity": proposal["approval_id"],
            "runtime_interface": plan["proposed_runtime_interface"], "last_verified_at": now, "health": UNKNOWN,
            "status": "ACTIVE_CAPABILITY", "available": True, "requires_approval": False, "verification_valid": True}
        def mutate(current: dict[str, Any]) -> None:
            car = current["autonomous_research"]
            car["capabilities"].append(row)
            p = next(x for x in car["proposals"] if x.get("proposal_id") == proposal_id); p["status"] = "ACTIVATED"
            target = next(x for x in car["tools"] if x.get("capability_id") == proposal["capability_id"])
            target.update(status="ACTIVE_CAPABILITY", discovery_state="ACTIVE_CAPABILITY", available=True, requires_approval=False)
            self._audit_state(car, proposal["capability_id"], "ACTIVATED", {"proposal_id": proposal_id})
        self.store.update(mutate); return row

    def _bound(self, proposal: dict[str, Any], action: str, state: dict[str, Any]):
        if proposal.get("requested_action") != action or proposal.get("status") != "APPROVED_PENDING_EXECUTOR":
            raise RuntimeError("Exact approved proposal required")
        ar = state["autonomous_research"]
        plan = next((x for x in ar["integration_plans"] if x.get("integration_plan_id") == proposal.get("integration_plan_id") and x.get("current") is True), None)
        approval = next((x for x in state["approvals"] if x.get("id") == proposal.get("approval_id")), None)
        tool = next((x for x in ar["tools"] if x.get("capability_id") == proposal.get("capability_id")), None)
        evaluation = next((x for x in ar["evaluations"] if x.get("capability_id") == proposal.get("capability_id") and x.get("current") is True), None)
        if not plan or not approval or approval.get("status") != "APPROVED" or not tool or not evaluation: raise RuntimeError("Stale lifecycle binding")
        expected = {key: proposal.get(key) for key in ("proposal_id", "integration_plan_id", "integration_plan_fingerprint", "capability_id",
                    "evaluation_fingerprint", "sandbox_verification_identity", "requested_action")}
        if any(approval.get("binding", {}).get(k) != v for k, v in expected.items()): raise RuntimeError("Approval replay/binding mismatch")
        if plan.get("integration_plan_fingerprint") != proposal.get("integration_plan_fingerprint") or evaluation.get("evaluation_fingerprint") != proposal.get("evaluation_fingerprint"):
            raise RuntimeError("Stale fingerprint")
        if self._repo(plan) != self._repo(proposal) or self._repo(tool) != self._repo(plan): raise RuntimeError("Repository mismatch")
        sandbox = next((x for x in ar["proposals"] if x.get("capability_id") == proposal.get("capability_id")
                        and x.get("requested_action") == "SANDBOX_VERIFICATION"
                        and x.get("evaluation_fingerprint") == evaluation.get("evaluation_fingerprint")
                        and x.get("status") == "SANDBOX_VERIFIED"), None)
        if not sandbox:
            raise RuntimeError("Stale sandbox result")
        sandbox_identity = _fingerprint({"proposal_id": sandbox["proposal_id"],
                                         "evaluation_fingerprint": evaluation["evaluation_fingerprint"],
                                         "result": sandbox.get("sandbox_result", {})})
        if sandbox_identity != plan.get("sandbox_verification_identity") or sandbox_identity != proposal.get("sandbox_verification_identity"):
            raise RuntimeError("Stale sandbox result")
        return plan, approval, tool, evaluation

    def _activation_preflight(self, capability_id: str, state: dict[str, Any], require_approval: bool) -> dict[str, Any]:
        ar = state["autonomous_research"]
        plan = next((x for x in ar["integration_plans"] if x.get("capability_id") == capability_id and x.get("current") is True), None)
        tool = next((x for x in ar["tools"] if x.get("capability_id") == capability_id), None)
        evaluation = next((x for x in ar["evaluations"] if x.get("capability_id") == capability_id and x.get("current") is True), None)
        verification = next((x for x in reversed(ar["integration_verifications"]) if plan and x.get("integration_plan_fingerprint") == plan.get("integration_plan_fingerprint")), None)
        if not plan or not tool or not evaluation or not verification or not verification.get("success"): raise RuntimeError("Successful current integration verification required")
        if tool.get("evaluation_fingerprint") != evaluation.get("evaluation_fingerprint"): raise RuntimeError("Canonical current evaluation required")
        if plan.get("proposed_runtime_interface") == UNKNOWN: raise RuntimeError("Runtime interface must be known")
        if any(x.get("severity") in {"HIGH", "CRITICAL"} and not x.get("resolved") for x in verification.get("result", {}).get("security_findings", [])):
            raise RuntimeError("Unresolved HIGH/CRITICAL security finding")
        for dep in plan.get("required_dependencies", []) + plan.get("required_system_dependencies", []):
            if dep.get("verified", UNKNOWN) is not True: raise RuntimeError("Required dependency is missing or UNKNOWN")
        creds = plan.get("credentials_required", {})
        if any(value is True for value in creds.values()) and verification.get("result", {}).get("credentials_connected") is not True:
            raise RuntimeError("Required credentials are not explicitly connected")
        return plan

    @staticmethod
    def _python_requirement(source: dict[str, Any], runtime: dict[str, Any]) -> str:
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        value = metadata.get("requires_python", UNKNOWN)
        if value != UNKNOWN: return value
        files = source.get("files") if isinstance(source.get("files"), dict) else {}
        try:
            project = tomllib.loads(str(files.get("pyproject.toml", ""))).get("project", {})
            if isinstance(project, dict) and project.get("requires-python"): return str(project["requires-python"])
        except (tomllib.TOMLDecodeError, AttributeError, TypeError):
            pass
        runtime_python = runtime.get("python", UNKNOWN)
        if isinstance(runtime_python, dict):
            return str(runtime_python.get("constraint", UNKNOWN))
        return runtime_python

    @staticmethod
    def _compatibility(requirement: str, env: dict[str, Any]) -> tuple[str, list[str]]:
        status, reason = python_constraint_compatibility(requirement, str(env.get("python", UNKNOWN)))
        return status, [reason]

    @staticmethod
    def _dependency_python_compatibility(requirements: dict[str, Any], env: dict[str, Any]) -> tuple[str, list[str]]:
        packages = requirements.get("packages", [])
        if not packages: return UNKNOWN, ["Dependency Python compatibility is not evidenced"]
        # Requirement markers can exclude a dependency, but do not prove that its release supports this interpreter.
        return UNKNOWN, ["Complete dependency set support for local Python is not independently evidenced"]

    @staticmethod
    def _risk(requirements: dict[str, Any], evaluation: dict[str, Any], compatibility: str,
              interface: dict[str, Any] | str, system: list[dict[str, Any]]) -> str:
        unknown_required = any(row.get("required") is True and row.get("verified", UNKNOWN) is not True for row in system)
        credential_state = {evaluation.get(key, UNKNOWN) for key in ("requires_api_key", "requires_account")}
        external_uncertainty = UNKNOWN in credential_state or evaluation.get("network_requirements", UNKNOWN) == UNKNOWN
        security = bool(evaluation.get("security_observations"))
        unresolved = (bool(requirements.get("risky_entries")) or compatibility != "COMPATIBLE" or interface == UNKNOWN
                      or unknown_required or True in credential_state or external_uncertainty or security)
        if unresolved or evaluation.get("risk_level") == "HIGH": return "HIGH"
        return evaluation.get("risk_level", UNKNOWN)

    @staticmethod
    def _optional_dependencies(source: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        values = metadata.get("optional_dependencies", [])
        return values if isinstance(values, list) else []

    @staticmethod
    def _repo(value: dict[str, Any]) -> str: return str(value.get("repository", "")).strip().casefold()

    @staticmethod
    def _audit_state(ar: dict[str, Any], capability_id: str, event: str, details: dict[str, Any]) -> None:
        ar["capability_audit"].append({"time": utc_now(), "capability_id": capability_id, "event": event, "details": details})

    @classmethod
    def _safe(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: cls._safe(v) for k, v in value.items() if not any(x in str(k).casefold() for x in ("secret", "token", "credential", "api_key", "authorization"))}
        if isinstance(value, list): return [cls._safe(x) for x in value]
        return value
