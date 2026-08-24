from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Protocol

from src.capabilities.capability_evaluator import PassiveCapabilityEvaluator, RepositoryEvidence

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SandboxExecutor(Protocol):
    """Approval-gated adapter. Production implementations may wrap the existing SandboxManager."""
    def verify(self, proposal: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]: ...


class CapabilityManager:
    """Lifecycle coordinator over the existing Control Center capability/approval store."""
    def __init__(self, store: Any, evaluator: PassiveCapabilityEvaluator | None = None) -> None:
        self.store = store
        self.evaluator = evaluator or PassiveCapabilityEvaluator()

    def evaluate(self, capability_id: str, evidence: RepositoryEvidence,
                 environment: dict[str, Any] | None = None) -> dict[str, Any]:
        state = self.store.snapshot(); research = state["autonomous_research"]
        candidate = next((x for x in research["tools"] if x.get("capability_id") == capability_id), None)
        if candidate is None: raise KeyError("Capability candidate not found")
        permit_retry = self._integration_failed_reevaluation_eligible(research, candidate)
        self._audit(capability_id, "EVALUATION_STARTED", {"repository": candidate.get("repository")})
        result = self.evaluator.evaluate(candidate, evidence, environment,
                                          permit_failed_integration_reevaluation=permit_retry)
        fingerprint = result["evaluation_fingerprint"]
        def mutate(current: dict[str, Any]) -> None:
            ar = current["autonomous_research"]
            old = next((x for x in ar["evaluations"] if x.get("capability_id") == capability_id and x.get("current")), None)
            if old and old.get("evaluation_fingerprint") == fingerprint:
                result.update(old); return
            if old: old["current"] = False
            result["current"] = True; ar["evaluations"].append(result)
            tool = next(x for x in ar["tools"] if x.get("capability_id") == capability_id)
            tool.update(status="EVALUATED_CANDIDATE", discovery_state="EVALUATED_CANDIDATE", available=False,
                        evaluation_fingerprint=fingerprint, project_type=result["project_type"])
            if result["recommended_action"] == "REQUEST_APPROVAL_FOR_SANDBOX":
                self._proposal(current, tool, result, old)
        self.store.update(mutate)
        self._audit(capability_id, "EVALUATION_COMPLETED", {"classification": result["project_type"],
            "compatibility": result["jarvis_environment_compatibility"], "risk": result["risk_level"],
            "recommendation": result["recommended_action"], "sources_inspected": len(result["evidence"])})
        return result

    @staticmethod
    def _integration_failed_reevaluation_eligible(research: dict[str, Any], candidate: dict[str, Any]) -> bool:
        """An INTEGRATION_FAILED candidate may only re-enter passive (read-only) evaluation
        when a still-current, exactly-bound SANDBOX_VERIFIED result already exists for it.
        This recovers a stuck evaluate/evidence-refresh path without resurrecting, reusing,
        or executing any prior sandbox/integration/approval state."""
        if candidate.get("status") != "INTEGRATION_FAILED" or candidate.get("discovery_state") != "INTEGRATION_FAILED":
            return False
        capability_id = candidate.get("capability_id")
        fingerprint = candidate.get("evaluation_fingerprint")
        if not fingerprint:
            return False
        evaluation = next((x for x in research.get("evaluations", [])
                           if x.get("capability_id") == capability_id and x.get("current") is True), None)
        if not evaluation or evaluation.get("evaluation_fingerprint") != fingerprint:
            return False
        repo = str(candidate.get("repository", "")).strip().casefold()
        if not repo:
            return False
        sandbox_proposal = next((x for x in reversed(research.get("proposals", []))
                                 if x.get("capability_id") == capability_id
                                 and x.get("requested_action") == "SANDBOX_VERIFICATION"
                                 and x.get("status") == "SANDBOX_VERIFIED"
                                 and x.get("evaluation_fingerprint") == fingerprint
                                 and str(x.get("repository", "")).strip().casefold() == repo), None)
        return sandbox_proposal is not None

    def _proposal(self, state: dict[str, Any], tool: dict[str, Any], evaluation: dict[str, Any], old: dict | None) -> None:
        ar = state["autonomous_research"]; fingerprint = evaluation["evaluation_fingerprint"]
        proposal_id = "capability-sandbox-" + hashlib.sha256(f"{tool['capability_id']}:{fingerprint}".encode()).hexdigest()[:24]
        if any(x.get("proposal_id") == proposal_id for x in ar["proposals"]): return
        previous = next((x for x in reversed(ar["proposals"]) if x.get("capability_id") == tool["capability_id"]), None)
        if previous and previous.get("status") == "PENDING": previous["status"] = "SUPERSEDED"
        approval_id = "approval-" + proposal_id
        proposal = {"proposal_id": proposal_id, "id": proposal_id, "capability_id": tool["capability_id"],
            "evaluation_fingerprint": fingerprint, "supersedes_proposal_id": previous.get("proposal_id") if previous else None,
            "tool": tool.get("name"), "repository": tool.get("repository"), "requested_action": "SANDBOX_VERIFICATION",
            "reason": tool.get("description", "Evaluate a verified candidate in isolation"),
            "purpose": evaluation["verified_capabilities"] or evaluation["claimed_capabilities"],
            "evidence": evaluation["evidence"], "license": evaluation["license"], "dependencies": evaluation["dependencies"],
            "hardware_requirements": evaluation["hardware_requirements"], "network_requirements": evaluation["network_requirements"],
            "requires_api_key": evaluation["requires_api_key"], "requires_account": evaluation["requires_account"],
            "requires_payment": evaluation["requires_payment"], "risk": evaluation["risk_level"],
            "sandbox_plan": ["controlled fetch/clone", "static dependency inspection", "security scan", "risk review"],
            "side_effects_if_approved": ["temporary isolated workspace write", "network repository fetch"],
            "rejection_effect": "No filesystem, environment, credential, account, or network change",
            "approval_id": approval_id, "status": "PENDING", "created_at": utc_now()}
        ar["proposals"].append(proposal)
        tool.update(status="APPROVAL_REQUIRED", discovery_state="APPROVAL_REQUIRED", requires_approval=True, available=False)
        state["approvals"].append({"id": approval_id, "type": "capability_proposal", "status": "PENDING",
            "what": f"Sandbox verification: {tool.get('name')}", "why": proposal["reason"], "risk": proposal["risk"],
            "cost": "UNKNOWN", "expected_result": "APPROVED_PENDING_EXECUTOR", "details": proposal,
            "binding": {"proposal_id": proposal_id, "capability_id": tool["capability_id"],
                        "requested_action": "SANDBOX_VERIFICATION", "evaluation_fingerprint": fingerprint},
            "created_at": utc_now()})

    def execute_approved(self, proposal_id: str, executor: SandboxExecutor) -> dict[str, Any]:
        state = self.store.snapshot(); ar = state["autonomous_research"]
        proposal = next((x for x in ar["proposals"] if x.get("proposal_id") == proposal_id), None)
        if not proposal or proposal.get("status") != "APPROVED_PENDING_EXECUTOR":
            raise RuntimeError("Approval required before sandbox executor")
        if proposal.get("requested_action") != "SANDBOX_VERIFICATION":
            raise RuntimeError("Approval replay/binding mismatch")
        candidate = next((x for x in ar["tools"] if x.get("capability_id") == proposal.get("capability_id")), None)
        if candidate is None or str(candidate.get("repository", "")).strip().casefold() != str(proposal.get("repository", "")).strip().casefold():
            raise RuntimeError("Canonical candidate binding mismatch")
        approval = next((x for x in state["approvals"] if x.get("id") == proposal.get("approval_id")), None)
        if not approval or approval.get("status") != "APPROVED": raise RuntimeError("Bound approval is not approved")
        binding = approval.get("binding", {})
        expected_binding = {
            "proposal_id": proposal_id,
            "capability_id": proposal.get("capability_id"),
            "requested_action": proposal.get("requested_action"),
            "evaluation_fingerprint": proposal.get("evaluation_fingerprint"),
        }
        if any(binding.get(key) != value for key, value in expected_binding.items()):
            raise RuntimeError("Approval replay/binding mismatch")
        evaluation = next((x for x in ar["evaluations"]
                           if x.get("evaluation_fingerprint") == proposal["evaluation_fingerprint"]
                           and x.get("capability_id") == proposal.get("capability_id")
                           and x.get("current") is True), None)
        if evaluation is None:
            raise RuntimeError("Current evaluation binding mismatch")
        outcome = executor.verify(proposal, evaluation)
        def mutate(current: dict[str, Any]) -> None:
            p = next(x for x in current["autonomous_research"]["proposals"] if x["proposal_id"] == proposal_id)
            p["status"] = "SANDBOX_VERIFIED" if outcome.get("success") else "SANDBOX_FAILED"
            p["sandbox_result"] = self._safe_result(outcome)
            tool = next(x for x in current["autonomous_research"]["tools"] if x["capability_id"] == p["capability_id"])
            tool.update(status=p["status"], discovery_state=p["status"], available=False)
        self.store.update(mutate)
        self._audit(proposal["capability_id"], "SANDBOX_RESULT", {"success": bool(outcome.get("success")), "active": False})
        return outcome

    def _audit(self, capability_id: str, event: str, details: dict[str, Any]) -> None:
        row = {"time": utc_now(), "capability_id": capability_id, "event": event, "details": details}
        self.store.update(lambda s: s["autonomous_research"]["capability_audit"].append(row))

    @classmethod
    def _safe_result(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: cls._safe_result(item) for key, item in value.items()
                    if not any(marker in str(key).casefold()
                               for marker in ("secret", "token", "credential", "api_key", "authorization"))}
        if isinstance(value, list):
            return [cls._safe_result(item) for item in value]
        return value
