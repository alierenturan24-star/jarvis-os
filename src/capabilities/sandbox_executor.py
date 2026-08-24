from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from src.evaluation.models import RepoEvaluation
from src.github.models import RepoData
from src.sandbox.models import SandboxMode, SandboxResult, SandboxStatus
from src.sandbox.sandbox_manager import SandboxManager


class CapabilitySandboxExecutor:
    """Production adapter from an approved capability proposal to SandboxManager."""

    def __init__(self, manager: SandboxManager | None = None) -> None:
        self.manager = manager or SandboxManager()

    @staticmethod
    def _canonical_repository(value: Any) -> tuple[str, str]:
        raw = str(value or "").strip()
        if raw.startswith("https://"):
            parsed = urlparse(raw)
            if parsed.scheme != "https" or parsed.netloc.casefold() != "github.com":
                raise RuntimeError("Repository identity mismatch")
            raw = parsed.path.strip("/")
        if raw.casefold().endswith(".git"):
            raw = raw[:-4]
        parts = raw.split("/")
        if len(parts) != 2 or not all(parts):
            raise RuntimeError("Repository identity mismatch")
        identity = f"{parts[0]}/{parts[1]}"
        return identity.casefold(), f"https://github.com/{identity}"

    def verify(self, proposal: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
        result: SandboxResult | None = None
        outcome: dict[str, Any]
        try:
            proposal_identity, repository_url = self._canonical_repository(proposal.get("repository"))
            evaluation_identity, _ = self._canonical_repository(evaluation.get("repository"))
            if proposal_identity != evaluation_identity:
                raise RuntimeError("Repository identity mismatch")
            for evidence in evaluation.get("evidence", []):
                evidence_url = evidence.get("url") if isinstance(evidence, dict) else None
                if evidence_url and self._canonical_repository(evidence_url)[0] != proposal_identity:
                    raise RuntimeError("Repository evidence identity mismatch")

            score = max(0.0, min(100.0, float(evaluation.get("confidence", 0.0)) * 100.0))
            compatible = evaluation.get("jarvis_environment_compatibility") != "INCOMPATIBLE"
            repo_evaluation = RepoEvaluation(
                name=proposal_identity, url=repository_url,
                overall_score=score, architecture_score=score, activity_score=score,
                community_score=score, license_score=score, security_score=score,
                compatibility_score=score, maintenance_score=score, relevance_score=score,
                recommendation=str(evaluation.get("recommended_action", "")),
                suitable_for_jarvis=compatible, target_module="capabilities",
                integration_difficulty="UNKNOWN", risk_level=str(evaluation.get("risk_level", "HIGH")),
            )
            license_data = evaluation.get("license") if isinstance(evaluation.get("license"), dict) else {}
            repo = RepoData(
                name=proposal_identity.split("/", 1)[1], full_name=proposal_identity,
                url=repository_url, description=str(proposal.get("reason", "")), stars=0, forks=0,
                license=str(license_data.get("license_name", "")), last_update="UNKNOWN",
                language="", category="capability",
            )
            result = self.manager.run_pipeline(
                repository_url, repo_evaluation, repo=repo,
                mode=SandboxMode.STATIC_ANALYSIS, approved_for_isolated_execution=False,
            )
            outcome = self._outcome(result)
        except Exception as error:
            outcome = {"success": False, "status": "failed", "error_type": type(error).__name__,
                       "error": str(error)[:400]}
        finally:
            if result is not None:
                try:
                    self.manager.cleanup(result)
                except Exception as error:
                    outcome = {"success": False, "status": "failed", "error_type": type(error).__name__,
                               "error": "Sandbox cleanup failed"}
        return outcome

    @staticmethod
    def _outcome(result: SandboxResult) -> dict[str, Any]:
        return {
            "success": result.status == SandboxStatus.READY_FOR_REVIEW,
            "status": result.status.value,
            "mode": result.mode.value,
            "repository": result.repository_name,
            "files_scanned": result.files_scanned,
            "total_size_mb": result.total_size_mb,
            "detected_language": result.detected_language,
            "detected_manifests": list(result.detected_manifests),
            "suspicious_files": list(result.suspicious_files),
            "suspicious_patterns": list(result.suspicious_patterns),
            "network_risk": result.network_risk,
            "execution_risk": result.execution_risk,
            "dependency_risk": result.dependency_risk,
            "license_detected": result.license_detected,
            "findings": list(result.findings),
            "recommended_action": result.recommended_action,
            "error": str(result.error)[:400] if result.error else None,
        }
