from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from src.github.client import GitHubClient


TRUST_BOUNDARY = "UNTRUSTED_EXTERNAL_CONTENT"
MAX_CONTENT_BYTES = 256_000
MAX_FILES = 20
MAX_CLAIMED_ENTRY_FILES = 8
CONTENT_PATHS = (
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "package.json",
    "environment.yml", "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING",
    "__main__.py", "main.py", "app.py", "cli.py",
)


class RepositoryEvidenceAcquisitionError(RuntimeError):
    pass


class RepositoryEvidenceAcquirer:
    """Bounded GitHub API reader. Repository bytes are data and are never executed."""

    def __init__(self, client: GitHubClient | None = None) -> None:
        self.client = client or GitHubClient(timeout=8)

    def acquire(self, repository: str, repository_url: str = "") -> dict[str, Any]:
        full_name = self._canonical_name(repository, repository_url)
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        repo = self._object(self.client.get(f"/repos/{full_name}"), "repository metadata")
        if str(repo.get("full_name", "")).casefold() != full_name.casefold():
            raise RepositoryEvidenceAcquisitionError("GitHub repository identity mismatch")
        canonical_url = str(repo.get("html_url") or f"https://github.com/{full_name}")
        self._canonical_name(full_name, canonical_url)

        items: list[dict[str, Any]] = []
        files: dict[str, str] = {}
        readme = ""
        readme_payload = self._optional(f"/repos/{full_name}/readme")
        if readme_payload:
            readme = self._decode_content(readme_payload, "README")
            items.append(self._item(canonical_url, readme_payload, "README", readme, retrieved_at))

        for path in CONTENT_PATHS[:MAX_FILES]:
            payload = self._optional(f"/repos/{full_name}/contents/{path}")
            if not payload:
                continue
            content = self._decode_content(payload, path)
            files[path] = content
            items.append(self._item(canonical_url, payload, "LICENSE" if path.upper().startswith(("LICENSE", "COPYING")) else "MANIFEST", content, retrieved_at, path))

        # README paths are claims, not authority. Only a small set of validated,
        # repository-relative Python candidates is checked through the same
        # read-only GitHub Contents API.
        for path in self._claimed_python_paths(readme)[:MAX_CLAIMED_ENTRY_FILES]:
            if path in files:
                continue
            payload = self._optional(f"/repos/{full_name}/contents/{path}")
            if not payload:
                continue
            content = self._decode_content(payload, path)
            files[path] = content
            items.append(self._item(canonical_url, payload, "CLAIMED_ENTRY_FILE", content, retrieved_at, path))

        commit = self._optional(f"/repos/{full_name}/commits/{repo.get('default_branch') or 'HEAD'}")
        release = self._optional(f"/repos/{full_name}/releases/latest")
        github_license = repo.get("license") if isinstance(repo.get("license"), dict) else {}
        metadata = {
            "owner/name": full_name, "canonical_url": canonical_url, "description": repo.get("description") or "",
            "default_branch": repo.get("default_branch") or "UNKNOWN", "archived": bool(repo.get("archived")),
            "fork": bool(repo.get("fork")), "stars": repo.get("stargazers_count", "UNKNOWN"),
            "latest_commit": self._commit_time(commit),
            "latest_release": (release or {}).get("tag_name", "UNKNOWN"),
            "license": github_license.get("spdx_id") or github_license.get("name") or "UNKNOWN",
            "claimed_capabilities": self._claimed(" ".join((str(repo.get("description") or ""), readme))),
            "verified_capabilities": self._verified(files),
        }
        metadata_item = self._item(canonical_url, repo, "REPOSITORY_METADATA", str(repo), retrieved_at)
        items.insert(0, metadata_item)
        return {"repository_url": canonical_url, "readme": readme, "files": files, "metadata": metadata,
                "evidence_items": items, "retrieved_at": retrieved_at, "trust_boundary": TRUST_BOUNDARY,
                "acquisition_status": "COMPLETE"}

    def _optional(self, path: str) -> dict[str, Any] | None:
        try:
            value = self.client.get(path)
        except Exception as error:
            # Missing optional files/releases are normal; rate limits, timeouts and malformed
            # responses remain visible in the top-level audit if acquisition cannot proceed.
            if "bulunamad" in str(error).casefold() or "not found" in str(error).casefold():
                return None
            raise RepositoryEvidenceAcquisitionError(f"Read-only GitHub acquisition failed: {type(error).__name__}: {error}") from error
        return self._object(value, path)

    @staticmethod
    def _object(value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise RepositoryEvidenceAcquisitionError(f"Malformed GitHub response for {label}")
        return value

    @staticmethod
    def _canonical_name(repository: str, repository_url: str) -> str:
        name = repository.strip().strip("/")
        if repository_url:
            parsed = urlparse(repository_url)
            if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"} or parsed.username or parsed.password or parsed.port:
                raise RepositoryEvidenceAcquisitionError("Repository URL is outside the canonical GitHub trust boundary")
            url_name = parsed.path.strip("/")
            if url_name.endswith(".git"): url_name = url_name[:-4]
            if name and url_name.casefold() != name.casefold():
                raise RepositoryEvidenceAcquisitionError("Candidate repository identity mismatch")
            name = url_name
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
            raise RepositoryEvidenceAcquisitionError("Invalid canonical GitHub owner/name")
        return name

    @staticmethod
    def _decode_content(payload: dict[str, Any], path: str) -> str:
        if payload.get("type", "file") != "file" or payload.get("encoding") != "base64":
            raise RepositoryEvidenceAcquisitionError(f"Unexpected content type for {path}")
        declared = payload.get("size")
        if isinstance(declared, int) and declared > MAX_CONTENT_BYTES:
            raise RepositoryEvidenceAcquisitionError(f"Oversized repository content rejected: {path}")
        try:
            # GitHub's Contents API may line-wrap base64. Remove only ASCII
            # whitespace, then retain strict alphabet and padding validation.
            encoded = str(payload.get("content", "")).translate(
                {ord(character): None for character in " \t\r\n\v\f"}
            )
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as error:
            raise RepositoryEvidenceAcquisitionError(f"Malformed repository content: {path}") from error
        if len(raw) > MAX_CONTENT_BYTES or b"\x00" in raw:
            raise RepositoryEvidenceAcquisitionError(f"Oversized or binary repository content rejected: {path}")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RepositoryEvidenceAcquisitionError(f"Non-text repository content rejected: {path}") from error

    @staticmethod
    def _item(url: str, payload: dict[str, Any], evidence_type: str, content: str, retrieved_at: str, path: str = "") -> dict[str, Any]:
        actual_path = path or str(payload.get("path") or evidence_type)
        return {"source_url": str(payload.get("html_url") or f"{url}/blob/HEAD/{actual_path}"),
                "source_identity": url, "retrieved_at": retrieved_at, "verification_state": "VERIFIED_GITHUB_API",
                "trust_boundary": TRUST_BOUNDARY, "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "evidence_type": evidence_type, "path": actual_path}

    @staticmethod
    def _commit_time(commit: dict[str, Any] | None) -> str:
        if not commit: return "UNKNOWN"
        value = commit.get("commit", {})
        if not isinstance(value, dict): return "UNKNOWN"
        committer = value.get("committer", {})
        return committer.get("date", "UNKNOWN") if isinstance(committer, dict) else "UNKNOWN"

    @staticmethod
    def _claimed(text: str) -> list[str]:
        folded = text.casefold()
        mapping = {"command-line interface": ("command line", "cli"), "subtitle generation": ("subtitle",),
                   "audio dubbing": ("dubbing", "dub audio"), "video generation": ("video generation", "text-to-video")}
        return [name for name, markers in mapping.items() if any(marker in folded for marker in markers)]

    @staticmethod
    def _claimed_python_paths(text: str) -> list[str]:
        candidates = re.findall(r"(?<![\w./\\:$@(])([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.py)(?![\w/])", text)
        safe: list[str] = []
        for path in candidates:
            if (path.startswith(("/", "\\")) or ".." in path.split("/") or ":" in path
                    or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.py", path)):
                continue
            if path not in safe:
                safe.append(path)
        return safe

    @staticmethod
    def _verified(files: dict[str, str]) -> list[str]:
        result = []
        if any(name in files for name in ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg")):
            result.append("Python project structure")
        if "package.json" in files: result.append("Node.js project structure")
        if "Dockerfile" in files: result.append("Container build definition")
        return result
