from __future__ import annotations

import json
import os
import threading
import shutil
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_STATE: dict[str, Any] = {
    "schema_version": 5,
    "engines": {
        "youtube": {"enabled": False, "queue": [], "policy": {"research": True, "production": True, "publish_requires_approval": True}},
        "finance": {"enabled": False, "mode": "RESEARCH", "watchlist": [], "live_activation": False,
                    "policy": {"research": True, "backtest": True, "paper": True, "real_orders": False,
                               "live_requires_human_approval": True}},
    },
    "missions": [],
    "approvals": [],
    "notifications": [],
    "settings": {"local_url": "http://127.0.0.1:8765", "remote_public_exposure": False},
    "paper": {"initial_cash": 10000.0, "cash": 10000.0, "positions": [], "closed": [], "currency": "USD",
              "performance": {}},
    "backtests": [],
    "strategy_labs": [],
    "finance_exploration": {"candidates": {}, "runs": [], "last_learning": None,
                            "next_exploration": []},
    "youtube_learning": {
        "productions": [], "characters": {}, "experiments": [],
        "learned_patterns": [], "next_production_changes": [],
        "analytics": {"source": "NOT_CONNECTED", "records": []},
    },
    "workforce": {"workers": {}, "decisions": [], "schedule_executions": [],
                  "cleanup_audits": [], "active_channel_id": None},
    "channels": {},
    "account_assignments": [],
    "publications": [],
    "autonomous_research": {"topics": [], "cycles": [], "findings": [], "tools": [], "capabilities": [],
                            "evaluations": [], "capability_audit": [], "proposals": [],
                            "integration_plans": [], "integration_verifications": []},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Sprint: research/production pipeline audit -- state-write concurrency fix.
# A real workforce run failed with [WinError 5] Access is denied writing
# 'state.tmp' -> 'state.json'. Root cause: every ControlCenterStore(...)
# instantiation created its OWN ``threading.RLock()``, which only
# serializes writes made through THAT one object -- useless against the
# actual pattern in this codebase, where department/workforce/media code
# paths each construct a FRESH ControlCenterStore() pointed at the SAME
# workspace/control_center/state.json (e.g. MediaManager.set_channel_scope,
# YouTubeLearningAgent.__init__ both do this). A single process-wide lock,
# shared by every instance, is the smallest fix that actually serializes the
# real read-modify-write-and-replace cycle across all of them -- no second
# state store, no new locking primitive/architecture, same public API.
_STATE_WRITE_LOCK = threading.RLock()


class ControlCenterStore:
    """Small atomic JSON store following the repository's existing storage pattern."""

    def __init__(self, path: str | Path = "workspace/control_center/state.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = _STATE_WRITE_LOCK
        with self._lock:
            if not self.path.exists():
                self._write(deepcopy(DEFAULT_STATE))
            else:
                self._recover_corruption_if_needed()

    def _recover_corruption_if_needed(self) -> None:
        """Quarantine unreadable state and start explicitly fail-closed."""
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Control Center state root must be an object")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            quarantine = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
            try:
                shutil.copy2(self.path, quarantine)
            except OSError:
                quarantine = None
            state = deepcopy(DEFAULT_STATE)
            state["state_integrity"] = {
                "status": "CORRUPTED_RECOVERY_REQUIRED",
                "detected_at": utc_now(),
                "error_type": type(error).__name__,
                "message": str(error),
                "quarantine": str(quarantine) if quarantine else None,
                "approval_state_trusted": False,
            }
            state["notifications"].append({
                "type": "ERROR", "created_at": utc_now(),
                "message": "Control Center state was corrupted; approvals and side effects are disabled pending review.",
            })
            state["engines"]["youtube"]["enabled"] = False
            state["engines"]["finance"]["enabled"] = False
            state["engines"]["finance"]["live_activation"] = False
            self._write(state)

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                return deepcopy(DEFAULT_STATE)
            # Forward-fill newly introduced fields without discarding persisted history.
            merged = deepcopy(DEFAULT_STATE)
            for key, item in value.items():
                if isinstance(item, dict) and isinstance(merged.get(key), dict): merged[key].update(item)
                else: merged[key] = item
            merged["engines"]["finance"].setdefault("policy", deepcopy(DEFAULT_STATE["engines"]["finance"]["policy"]))
            merged["paper"].setdefault("initial_cash", 10000.0); merged["paper"].setdefault("performance", {})
            research = merged.setdefault("autonomous_research", {})
            for key in ("topics", "cycles", "findings", "tools", "capabilities", "evaluations", "capability_audit", "proposals",
                        "integration_plans", "integration_verifications"):
                research.setdefault(key, [])
            return merged
        except (OSError, UnicodeError, ValueError) as error:
            raise RuntimeError(f"Control Center state cannot be read safely: {error}") from error

    def _write(self, value: dict[str, Any]) -> None:
        # Sprint: research/production pipeline audit -- each write used a
        # FIXED 'state.tmp' path shared by every writer; on Windows this is
        # what actually produced the real [WinError 5] Access is denied
        # (concurrent writers' write/rename windows overlapped on the SAME
        # filename, which Windows locks more strictly than POSIX). Each
        # write now uses its own uniquely-named temp file (pid+thread+uuid),
        # so concurrent writers -- even ones reached without the shared
        # lock above -- never contend for the same filename. os.replace()
        # is still the single atomic publish step onto the real path, so
        # crash safety and the on-disk schema are unchanged.
        temporary = self.path.with_name(
            f"{self.path.stem}.{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex[:8]}.tmp"
        )
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            # A transient WinError 5 (Access is denied) can still occur here
            # even with a uniquely-named temp file -- observed under real
            # load, consistent with something else briefly holding a handle
            # on the freshly-written temp file (e.g. AV/indexer scanning a
            # new small file), not a logic race (this write already holds
            # the shared lock and owns an exclusive filename). A short
            # bounded retry absorbs that without masking a real, persistent
            # failure (still raises after exhausting the retries).
            last_error: OSError | None = None
            for attempt in range(5):
                try:
                    os.replace(temporary, self.path)
                    last_error = None
                    break
                except OSError as error:
                    last_error = error
                    if attempt < 4:
                        time.sleep(0.02 * (attempt + 1))
            if last_error is not None:
                raise last_error
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._read())

    def update(self, mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            mutator(state)
            self._write(state)
            return deepcopy(state)

    def append(self, collection: str, item: dict[str, Any], limit: int = 250) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> None:
            values = state.setdefault(collection, [])
            values.append(item)
            del values[:-limit]
        return self.update(mutate)

    def recover_interrupted(self) -> list[str]:
        """Mark work left active by a dead process without claiming success."""
        recovered: list[str] = []
        def mutate(state: dict[str, Any]) -> None:
            for mission in state.setdefault("missions", []):
                if mission.get("status") in {"QUEUED", "WORKING", "DISPATCHED"}:
                    mission.update(status="INTERRUPTED", stage="RECOVERY REQUIRED",
                                   finished_at=utc_now(), recovery_required=True)
                    recovered.append(str(mission.get("id", "")))
            for item in state.setdefault("engines", {}).setdefault("youtube", {}).setdefault("queue", []):
                if item.get("status") == "DISPATCHED":
                    item.update(status="INTERRUPTED", recovery_required=True, interrupted_at=utc_now())
            for worker in state.setdefault("workforce", {}).setdefault("workers", {}).values():
                if worker.get("status") in {"RESEARCHING", "PLANNING", "WORKING", "VALIDATING"}:
                    worker.update(status="RECOVERY_REQUIRED", last_error="Interrupted during runtime restart",
                                  updated_at=utc_now())
        self.update(mutate)
        return recovered
