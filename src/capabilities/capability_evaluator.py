from __future__ import annotations

import hashlib
import json
import platform
import sys
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


UNKNOWN = "UNKNOWN"
PROJECT_TYPES = {"EXECUTABLE_TOOL", "LIBRARY", "MODEL", "CURATED_LIST", "DOCUMENTATION", "UNKNOWN"}
RECOMMENDATIONS = {"REJECT", "KEEP_FOR_REFERENCE", "REQUEST_APPROVAL_FOR_SANDBOX", "NEEDS_MORE_RESEARCH"}


@dataclass
class RepositoryEvidence:
    """Already-fetched, untrusted repository data. Evaluating it performs no I/O."""
    repository_url: str
    readme: str = ""
    files: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence_items: list[dict[str, Any]] = field(default_factory=list)


def local_environment() -> dict[str, Any]:
    """Small read-only view of facts already exposed by this runtime; unknowns stay unknown."""
    return {"os": platform.system() or UNKNOWN, "python": platform.python_version() or UNKNOWN,
            "node": UNKNOWN, "docker": UNKNOWN, "ffmpeg": UNKNOWN, "cuda": UNKNOWN,
            "gpu": UNKNOWN, "ram": UNKNOWN, "disk": UNKNOWN}


class PassiveCapabilityEvaluator:
    """Classifies supplied repository evidence as data; never fetches or executes content."""

    def evaluate(self, candidate: dict[str, Any], evidence: RepositoryEvidence,
                 environment: dict[str, Any] | None = None, *,
                 permit_failed_integration_reevaluation: bool = False) -> dict[str, Any]:
        allowed = {"VERIFIED_CANDIDATE", "EVALUATED_CANDIDATE", "APPROVAL_REQUIRED"}
        status, discovery_state = candidate.get("status"), candidate.get("discovery_state")
        # A caller may set this only after independently proving the INTEGRATION_FAILED
        # candidate still has a current, exactly-bound SANDBOX_VERIFIED result (see
        # CapabilityManager._integration_failed_reevaluation_eligible). This never widens
        # the gate on its own: without that upstream proof, INTEGRATION_FAILED stays rejected.
        recoverable_failure = (permit_failed_integration_reevaluation
                               and status == "INTEGRATION_FAILED" and discovery_state == "INTEGRATION_FAILED")
        if status not in allowed and discovery_state not in allowed and not recoverable_failure:
            raise RuntimeError("Only verified, evaluated, or approval-pending candidates may be evaluated")
        env = {**local_environment(), **(environment or {})}
        text = evidence.readme.casefold()
        names = {name.casefold(): value for name, value in evidence.files.items()}
        curated = any(marker in text for marker in ("awesome list", "curated list", "curated collection")) or (
            candidate.get("repository", "").casefold().split("/")[-1].startswith("awesome-") and not self._has_runtime_manifest(names))
        docs_only = bool(names) and all(name.endswith((".md", ".rst", ".txt")) for name in names)
        executable = self._has_runtime_manifest(names) and any(marker in text for marker in
            ("install", "usage", "quick start", "command line", "run ", "python ", "docker"))
        library = not executable and any(name in names for name in ("pyproject.toml", "setup.py", "package.json"))
        model = any(name.endswith((".safetensors", ".ckpt", ".onnx")) for name in names)
        project_type = ("CURATED_LIST" if curated else "MODEL" if model else "EXECUTABLE_TOOL" if executable
                        else "LIBRARY" if library else "DOCUMENTATION" if docs_only else "UNKNOWN")

        license_path = next((n for n in names if n.rsplit("/", 1)[-1] in {"license", "license.md", "license.txt", "copying"}), None)
        license_name = evidence.metadata.get("license") or self._detect_license(names)
        detected = bool(license_path or license_name != UNKNOWN)
        dependencies = self._dependencies(names)
        cuda = self._cuda_requirement(text)
        python_requirement = self._python_requirement(evidence)
        runtime = {"python": python_requirement, "node": self._value(text, "node"),
                   "docker": "REQUIRED" if "dockerfile" in names or "docker" in text else UNKNOWN,
                   "ffmpeg": "REQUIRED" if "ffmpeg" in text else UNKNOWN,
                   "cuda": cuda["classification"], "cuda_evidence": cuda, "other": []}
        requires_api_key = True if any(x in text for x in ("api key", "api_key", "apikey")) else UNKNOWN
        requires_account = True if any(x in text for x in ("create an account", "sign up", "login required")) else UNKNOWN
        requires_payment = True if any(x in text for x in ("paid plan", "subscription", "pricing")) else UNKNOWN
        gpu_required = "REQUIRED" if any(x in text for x in ("gpu required", "requires gpu", "cuda required")) else UNKNOWN
        hardware = {"cpu": UNKNOWN, "ram": UNKNOWN, "gpu": gpu_required, "vram": UNKNOWN, "disk": UNKNOWN}
        reasons: list[str] = []
        compatibility = "UNKNOWN"
        if runtime["python"] != UNKNOWN and env.get("python") != UNKNOWN:
            compatibility = "PARTIAL"; reasons.append("Python runtime is present; declared version fit was not proven")
        if gpu_required == "REQUIRED" and env.get("gpu", UNKNOWN) == UNKNOWN:
            compatibility = "UNKNOWN"; reasons.append("GPU/CUDA requirement cannot be verified from local inventory")
        if project_type in {"CURATED_LIST", "DOCUMENTATION"}:
            recommendation = "KEEP_FOR_REFERENCE"
        elif project_type in {"EXECUTABLE_TOOL", "LIBRARY", "MODEL"}:
            recommendation = "REQUEST_APPROVAL_FOR_SANDBOX" if detected else "NEEDS_MORE_RESEARCH"
        else:
            recommendation = "NEEDS_MORE_RESEARCH"
        risk = "HIGH" if not detected or requires_payment is True else "MEDIUM"
        confidence = .9 if project_type == "CURATED_LIST" else .75 if project_type != "UNKNOWN" else .35
        if not detected: confidence = max(0.0, confidence - .2)
        refs = [{"url": evidence.repository_url, "path": p, "sha256": hashlib.sha256(v.encode("utf-8")).hexdigest(),
                 "trust_boundary": "UNTRUSTED_EXTERNAL_CONTENT"} for p, v in sorted(evidence.files.items())]
        if evidence.readme:
            refs.append({"url": evidence.repository_url, "path": "README", "sha256": hashlib.sha256(evidence.readme.encode()).hexdigest(),
                         "trust_boundary": "UNTRUSTED_EXTERNAL_CONTENT"})
        for item in evidence.evidence_items:
            identity = (item.get("evidence_type"), item.get("path"), item.get("content_sha256"))
            if not any((row.get("evidence_type"), row.get("path"), row.get("content_sha256")) == identity for row in refs):
                refs.append(dict(item))
        result = {"capability_id": candidate["capability_id"], "repository": candidate.get("repository"),
                  "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "project_type": project_type,
                  "claimed_capabilities": list(evidence.metadata.get("claimed_capabilities", [])),
                  "verified_capabilities": list(evidence.metadata.get("verified_capabilities", [])), "evidence": refs,
                  "license": {"detected": detected, "license_name": license_name,
                              "license_url/path": license_path or UNKNOWN,
                              "commercial_use_status": evidence.metadata.get("commercial_use_status", UNKNOWN),
                              "redistribution_status": evidence.metadata.get("redistribution_status", UNKNOWN)},
                  "installation_method": self._installation(names), "dependencies": dependencies,
                  "external_services": list(evidence.metadata.get("external_services", [UNKNOWN])),
                  "requires_api_key": requires_api_key, "requires_account": requires_account,
                  "requires_payment": requires_payment, "hardware_requirements": hardware,
                  "runtime_requirements": runtime, "platform_support": evidence.metadata.get("platform_support", [UNKNOWN]),
                  "runtime_interface_claims": self._runtime_interface_claims(evidence),
                  "network_requirements": evidence.metadata.get("network_requirements", UNKNOWN),
                  "security_observations": (["Repository text contains command-like or prompt-injection content; retained only as untrusted evidence"]
                    if any(x in text for x in ("ignore previous instructions", "run powershell", "run this command")) else []),
                  "maintenance": {"latest_commit": evidence.metadata.get("latest_commit", UNKNOWN),
                                  "latest_release": evidence.metadata.get("latest_release", UNKNOWN),
                                  "archived": evidence.metadata.get("archived", UNKNOWN),
                                  "maintenance_status": evidence.metadata.get("maintenance_status", UNKNOWN)},
                  "jarvis_environment_compatibility": compatibility, "compatibility_reasons": reasons,
                  "risk_level": risk, "confidence": confidence, "recommended_action": recommendation}
        stable = {key: value for key, value in result.items() if key != "evaluated_at"}
        result["evaluation_fingerprint"] = hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()
        return result

    @staticmethod
    def _has_runtime_manifest(files: dict[str, str]) -> bool:
        return any(x in files for x in ("requirements.txt", "pyproject.toml", "package.json", "environment.yml", "dockerfile", "setup.py", "setup.cfg"))

    @staticmethod
    def _value(text: str, value: str) -> str:
        return "DECLARED" if value in text else UNKNOWN

    @staticmethod
    def _python_requirement(evidence: RepositoryEvidence) -> dict[str, Any] | str:
        match = re.search(r"\bpython\s*(?:version\s*)?(>=|<=|==|~=|>|<)\s*(\d+(?:\.\d+){0,2})", evidence.readme, re.I)
        if not match:
            return "DECLARED" if "python" in evidence.readme.casefold() else UNKNOWN
        constraint = "".join(match.groups())
        return {"declared": True, "constraint": constraint,
                "claim_type": "CLAIMED_RUNTIME_REQUIREMENT",
                "evidence_identity": hashlib.sha256(evidence.readme.encode()).hexdigest(),
                "verification": "REPOSITORY_CLAIM"}

    @staticmethod
    def _runtime_interface_claims(evidence: RepositoryEvidence) -> list[dict[str, Any]]:
        from src.capabilities.repository_evidence import RepositoryEvidenceAcquirer
        readme_identity = hashlib.sha256(evidence.readme.encode()).hexdigest()
        return [{"type": "PYTHON_SCRIPT", "entry_path": path, "claim_type": "README_ENTRYPOINT_CLAIM",
                 "evidence_identity": readme_identity, "verification": "CLAIMED_ONLY"}
                for path in RepositoryEvidenceAcquirer._claimed_python_paths(evidence.readme)]

    @staticmethod
    def _cuda_requirement(text: str) -> dict[str, str]:
        """Classify repository claims conservatively; mere CUDA mention proves nothing."""
        required = ("cuda required", "requires cuda", "cuda is required", "must have cuda", "cuda-only")
        optional = ("cuda optional", "optional cuda", "cuda is optional", "cpu fallback", "runs on cpu", "cpu-only mode")
        recommended = ("cuda recommended", "cuda is recommended", "gpu recommended", "recommended gpu", "for acceleration", "faster with cuda")
        if any(marker in text for marker in required):
            return {"classification": "REQUIRED", "basis": "EXPLICIT_REQUIRED_CLAIM"}
        if any(marker in text for marker in optional):
            return {"classification": "OPTIONAL", "basis": "OPTIONAL_OR_CPU_FALLBACK_CLAIM"}
        if any(marker in text for marker in recommended):
            return {"classification": "RECOMMENDED", "basis": "ACCELERATION_RECOMMENDATION"}
        return {"classification": UNKNOWN, "basis": "AMBIGUOUS_OR_NO_CLAIM"}

    @staticmethod
    def _installation(files: dict[str, str]) -> list[str]:
        mapping = {"requirements.txt": "PIP", "pyproject.toml": "PYTHON_PROJECT", "setup.py": "PYTHON_SETUP",
                   "setup.cfg": "PYTHON_SETUP", "package.json": "NPM", "environment.yml": "CONDA",
                   "dockerfile": "DOCKER", "docker-compose.yml": "DOCKER_COMPOSE", "docker-compose.yaml": "DOCKER_COMPOSE"}
        return [method for name, method in mapping.items() if name in files] or [UNKNOWN]

    @staticmethod
    def _dependencies(files: dict[str, str]) -> list[dict[str, str]]:
        rows = []
        for name in ("requirements.txt", "pyproject.toml", "package.json", "environment.yml", "setup.py", "setup.cfg"):
            if name in files:
                rows.append({"manifest": name, "sha256": hashlib.sha256(files[name].encode()).hexdigest(),
                             "packages": PassiveCapabilityEvaluator._package_names(name, files[name]),
                             "details": "UNTRUSTED_MANIFEST_NOT_EXECUTED"})
        return rows

    @staticmethod
    def _package_names(name: str, content: str) -> list[str]:
        """Conservative names only; manifest data is not imported or executed."""
        if name == "requirements.txt":
            return sorted({match.group(1) for line in content.splitlines()
                           if (match := re.match(r"\s*([A-Za-z0-9_.-]+)", line)) and not line.lstrip().startswith(("#", "-"))})[:100]
        if name == "package.json":
            try:
                value = json.loads(content)
                names = set()
                for key in ("dependencies", "devDependencies", "peerDependencies"):
                    if isinstance(value.get(key), dict): names.update(str(x) for x in value[key])
                return sorted(names)[:100]
            except (ValueError, AttributeError):
                return []
        return []

    @staticmethod
    def _detect_license(files: dict[str, str]) -> str:
        path = next((n for n in files if n.rsplit("/", 1)[-1] in {"license", "license.md", "license.txt", "copying"}), None)
        if not path: return UNKNOWN
        text = files[path].casefold()
        if "mit license" in text: return "MIT"
        if "apache license" in text and "version 2.0" in text: return "Apache-2.0"
        if "gnu general public license" in text: return "GPL"
        return UNKNOWN
