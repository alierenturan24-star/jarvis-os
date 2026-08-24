from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from src.control_center.store import utc_now


PUBLICATION_STATES = ("READY_FOR_APPROVAL", "APPROVED", "PUBLISHING", "REMOTE_VERIFYING", "PUBLISHED_VERIFIED")


def artifact_id(path: str | Path) -> str:
    candidate = Path(path)
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        while chunk := handle.read(1024 * 1024): digest.update(chunk)
    return digest.hexdigest()


class YouTubePublisher:
    def __init__(self, store, accounts) -> None:
        self.store, self.accounts = store, accounts

    def preflight(self, approval_id: str) -> dict[str, Any]:
        state = self.store.snapshot()
        approval = next((x for x in state["approvals"] if x["id"] == approval_id), None)
        if approval is None: raise KeyError("Approval not found")
        binding = approval.get("binding", {})
        required = {"artifact_id", "artifact_path", "production_id", "channel_id", "account_id", "worker_id"}
        if not required <= set(binding): raise RuntimeError("APPROVAL_BINDING_INCOMPLETE")
        path = Path(binding["artifact_path"])
        if not path.is_file() or artifact_id(path) != binding["artifact_id"]:
            raise RuntimeError("APPROVED_ARTIFACT_CHANGED")
        if approval.get("publication_claimed_at"):
            raise RuntimeError("APPROVAL_ALREADY_CONSUMED")
        if approval["status"] != "APPROVED":
            return {"status": "READY_FOR_APPROVAL", "publish_allowed": False, "reason": "HUMAN_APPROVAL_REQUIRED"}
        if not binding["account_id"]:
            return {"status": "ACCOUNT_NOT_CONNECTED", "publish_allowed": False}
        account = self.accounts.assert_scope(worker_id=binding["worker_id"], channel_id=binding["channel_id"],
            account_id=binding["account_id"], artifact_channel_id=binding["artifact_channel_id"])
        channel = state["channels"][binding["channel_id"]]
        today = utc_now()[:10]
        publications_today = sum(p.get("channel_id") == binding["channel_id"]
            and str(p.get("created_at", "")).startswith(today) for p in state.get("publications", []))
        if publications_today >= channel.get("limits", {}).get("daily_publication_budget", 1):
            return {"status": "PUBLICATION_BUDGET_LIMIT", "publish_allowed": False}
        return {"status": "APPROVED", "publish_allowed": True, "account_id": account["account_id"],
                "channel_id": binding["channel_id"], "production_id": binding["production_id"],
                "artifact_id": binding["artifact_id"]}

    def publish(self, approval_id: str, *, execute: bool = False) -> dict[str, Any]:
        preflight = self.preflight(approval_id)
        if not execute: return {**preflight, "dry_run": True, "real_publish_used": False}
        if not preflight.get("publish_allowed"): raise RuntimeError(preflight["status"])
        claimed: dict[str, Any] = {}
        def claim(state: dict[str, Any]) -> None:
            approval = next((x for x in state["approvals"] if x["id"] == approval_id), None)
            if approval is not None and approval.get("status") == "APPROVED":
                approval.update(status="PUBLISHING", publication_claimed_at=utc_now())
                claimed.update(approval)
        self.store.update(claim)
        if not claimed:
            raise RuntimeError("APPROVAL_ALREADY_CONSUMED")
        state = self.store.snapshot(); approval = claimed
        binding = approval["binding"]; account = self.accounts._raw(binding["account_id"])
        publication_id = uuid.uuid4().hex
        self._persist({"publication_id": publication_id, **binding, "publication_status": "PUBLISHING",
            "remote_verified": False, "created_at": utc_now(), "metadata": approval["publication_metadata"]})
        try:
            result = self.accounts.provider.upload_video(account["credential_ref"], artifact=binding["artifact_path"],
                                                          metadata=approval["publication_metadata"])
            remote_id = result.get("id")
            self._update(publication_id, publication_status="REMOTE_VERIFYING", remote_video_id=remote_id)
            verified = self.accounts.provider.verify_video(account["credential_ref"], remote_id)
            if not verified["verified"]:
                self._update(publication_id, publication_status="REMOTE_VERIFYING", remote_verified=False)
                return self._find(publication_id)
            self._update(publication_id, publication_status="PUBLISHED_VERIFIED", remote_verified=True,
                         verified_at=utc_now(), published_at=utc_now(),
                         remote_reference=f"youtube:video:{remote_id}")
            return self._find(publication_id)
        except Exception as error:
            self._update(publication_id, publication_status="PUBLICATION_FAILED", remote_verified=False,
                         failure_class=type(error).__name__)
            raise

    def _persist(self, row: dict) -> None: self.store.update(lambda s: s["publications"].append(row))
    def _update(self, publication_id: str, **fields) -> None:
        self.store.update(lambda s: next(x for x in s["publications"] if x["publication_id"] == publication_id).update(**fields))
    def _find(self, publication_id: str) -> dict:
        return next(x for x in self.store.snapshot()["publications"] if x["publication_id"] == publication_id)
