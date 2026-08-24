from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from typing import Any, Callable

from src.capabilities.sandbox_executor import CapabilitySandboxExecutor
from src.capabilities.integration_lifecycle import trusted_package_index, python_constraint_compatibility
from src.sandbox.fs_utils import safe_rmtree
from src.sandbox.models import SandboxStatus
from src.sandbox.sandbox_manager import SandboxManager


class ControlledCapabilityInstaller:
    """Execute an approved integration plan inside the existing sandbox boundary."""

    def __init__(self, manager: SandboxManager | None = None,
                 runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> None:
        self.manager = manager or SandboxManager(subprocess_env=self._credential_free_base_environment())
        self.runner = runner

    def verify(self, plan: dict[str, Any]) -> dict[str, Any]:
        result = None
        keep_environment = False
        try:
            self._preflight(plan)
            _identity, repository_url = CapabilitySandboxExecutor._canonical_repository(plan.get("repository"))
            result = self.manager.create(repository_url)
            result = self.manager.clone_repository(result)
            if result.status != SandboxStatus.ANALYZING:
                raise RuntimeError(result.error or "Repository isolation failed")
            result = self.manager.inspect(result)
            result = self.manager.detect_manifests(result)
            result = self.manager.scan_security(result)
            if result.status != SandboxStatus.ANALYZING:
                raise RuntimeError(result.error or "Sandbox inspection failed")
            if "HIGH" in {result.network_risk, result.execution_risk, result.dependency_risk}:
                raise RuntimeError("High-risk repository findings block controlled integration")

            root = Path(result.sandbox_path or "").resolve()
            environment = root / ".jarvis-venv"
            base_python = self._select_base_python(plan)
            self._create_venv(base_python, environment, root)
            python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            specs = [self._requirement(row) for row in plan.get("required_dependencies", [])]
            run_env = self._isolated_environment(environment)
            if specs:
                indexes = self._package_index_args(plan)
                indexed_specs, default_specs = self._partition_by_index_requirement(specs, indexes)
                if indexed_specs:
                    self._run([str(python), "-m", "pip", "install", "--disable-pip-version-check", *indexes, *indexed_specs], root, run_env, 600)
                if default_specs:
                    self._run([str(python), "-m", "pip", "install", "--disable-pip-version-check", *default_specs], root, run_env, 600)
            self._smoke_test(plan.get("proposed_runtime_interface"), python, root, run_env)
            keep_environment = True
            return {"success": True, "status": "integration_verified", "isolation": "venv_in_sandbox",
                    "runtime_interface": plan.get("proposed_runtime_interface"),
                    "verified_dependencies": [row["name"] for row in plan.get("required_dependencies", [])]
                    + [row["name"] for row in plan.get("required_system_dependencies", []) if row.get("verified") is True],
                    "security_findings": [], "model_downloaded": False, "credentials_used": False,
                    "environment_path": str(environment)}
        except Exception as error:
            return {"success": False, "status": "integration_failed", "error_type": type(error).__name__,
                    "error": str(error)[:400], "rolled_back": True, "model_downloaded": False,
                    "credentials_used": False, "security_findings": []}
        finally:
            if result is not None and result.sandbox_path and not keep_environment:
                safe_rmtree(result.sandbox_path)

    @staticmethod
    def _preflight(plan: dict[str, Any]) -> None:
        risky = plan.get("manifest_analysis", {}).get("risky_entries", [])
        if any(not trusted_package_index(str(row.get("value", ""))) for row in risky):
            raise RuntimeError("Risky dependency entries block controlled integration")
        if any(value is True for value in plan.get("credentials_required", {}).values()):
            raise RuntimeError("Credentials are not permitted during controlled integration")
        resources = plan.get("models/resources")
        if resources not in (None, "", "UNKNOWN", [], {}):
            raise RuntimeError("Model/resource download requires separate approval")
        if plan.get("proposed_runtime_interface") in (None, "", "UNKNOWN"):
            raise RuntimeError("Verified runtime interface required")

    @staticmethod
    def _package_index_args(plan: dict[str, Any]) -> list[str]:
        analysis = plan.get("manifest_analysis", {})
        indexes = list(analysis.get("package_indexes", []))
        indexes.extend(filter(None, (trusted_package_index(str(row.get("value", "")))
                                     for row in analysis.get("risky_entries", []))))
        unique = list(dict.fromkeys(indexes))
        if any(index != trusted_package_index(f"--index-url {index}") for index in unique):
            raise RuntimeError("Risky dependency entries block controlled integration")
        if len(unique) > 1:
            raise RuntimeError("Multiple dependency indexes are not permitted")
        return ["--index-url", unique[0]] if unique else []

    @staticmethod
    def _partition_by_index_requirement(specs: list[str], indexes: list[str]) -> tuple[list[str], list[str]]:
        """Only specs pinned with a PEP 440 local version (e.g. torch==2.5.1+cpu) can resolve on the
        trusted extra index; PyPI rejects local-version uploads, so anything else (soundfile, TTS, ...)
        must keep resolving against the default index or every non-index-hosted package fails outright."""
        if not indexes:
            return [], specs
        indexed = [spec for spec in specs if "+" in spec]
        default = [spec for spec in specs if spec not in indexed]
        return indexed, default

    def _select_base_python(self, plan: dict[str, Any]) -> str:
        required = plan.get("required_runtime", {})
        constraint = required.get("python") if isinstance(required, dict) else None
        if not isinstance(constraint, str) or constraint in ("", "UNKNOWN", "DECLARED"):
            return sys.executable
        status, _ = python_constraint_compatibility(constraint, platform.python_version())
        if status != "INCOMPATIBLE":
            return sys.executable
        candidate = self._find_installed_python(constraint)
        if candidate is None:
            raise RuntimeError(f"No installed Python satisfies required interpreter constraint '{constraint}' "
                                f"(Jarvis runtime is {platform.python_version()}); install a matching Python "
                                "and retry, Jarvis's own runtime will not be changed")
        return candidate

    def _find_installed_python(self, constraint: str) -> str | None:
        for minor in range(13, 7, -1):
            status, _ = python_constraint_compatibility(constraint, f"3.{minor}.0")
            if status != "COMPATIBLE":
                continue
            candidate = self._probe_python_launcher(3, minor)
            if candidate:
                return candidate
        return None

    def _probe_python_launcher(self, major: int, minor: int) -> str | None:
        if os.name == "nt" and shutil.which("py"):
            try:
                probe = self.runner(["py", f"-{major}.{minor}", "-c", "import sys; print(sys.executable)"],
                                     capture_output=True, text=True, timeout=15)
            except (OSError, subprocess.SubprocessError):
                probe = None
            if probe is not None and probe.returncode == 0 and probe.stdout.strip():
                return probe.stdout.strip()
        return shutil.which(f"python{major}.{minor}")

    def _create_venv(self, base_python: str, environment: Path, root: Path) -> None:
        if base_python == sys.executable:
            venv.EnvBuilder(with_pip=True, clear=False, symlinks=False).create(environment)
            return
        self._run([base_python, "-m", "venv", str(environment)], root, self._credential_free_base_environment(), 120)

    @staticmethod
    def _requirement(row: dict[str, Any]) -> str:
        name = str(row.get("name", "")); extras = str(row.get("extras", ""))
        constraint = "" if row.get("constraint") in (None, "", "UNKNOWN") else str(row["constraint"])
        marker = "" if row.get("marker") in (None, "", "UNKNOWN") else f"; {row['marker']}"
        if not name:
            raise RuntimeError("Invalid persisted dependency")
        return f"{name}{extras}{constraint}{marker}"

    @staticmethod
    def _credential_free_base_environment() -> dict[str, str]:
        allowed = {key: value for key, value in os.environ.items() if key.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT", "LANG", "LC_ALL"
        }}
        allowed.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"})
        return allowed

    @classmethod
    def _isolated_environment(cls, environment: Path) -> dict[str, str]:
        allowed = cls._credential_free_base_environment()
        allowed.update({"VIRTUAL_ENV": str(environment), "PYTHONNOUSERSITE": "1", "PIP_CONFIG_FILE": os.devnull,
                        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"})
        return allowed

    def _run(self, command: list[str], cwd: Path, env: dict[str, str], timeout: int) -> None:
        completed = self.runner(command, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout)
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "command failed").strip()[:300]
            raise RuntimeError(detail)

    def _smoke_test(self, interface: Any, python: Path, root: Path, env: dict[str, str]) -> None:
        paths: list[str] = []
        if isinstance(interface, dict):
            if interface.get("entry_path") and str(interface.get("entry_path")).endswith(".py"):
                paths.append(str(interface["entry_path"]))
            for row in interface.get("interfaces", []):
                if isinstance(row, dict) and str(row.get("entry_path", "")).endswith(".py"):
                    paths.append(str(row["entry_path"]))
        if paths:
            for relative in paths:
                target = (root / relative).resolve()
                try: target.relative_to(root)
                except ValueError: raise RuntimeError("Runtime interface escapes isolated repository")
                if not target.is_file(): raise RuntimeError("Runtime interface is missing")
                self._run([str(python), "-m", "py_compile", str(target)], root, env, 60)
        else:
            self._run([str(python), "-c", "import sys; assert sys.prefix != sys.base_prefix"], root, env, 60)
