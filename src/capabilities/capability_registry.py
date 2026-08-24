from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from src.capabilities.capability import Capability
from src.config.settings import Settings


class CapabilityRegistry:

    def __init__(self, store=None):

        self.capabilities = {}
        self.store = store

    def register(self, capability: Capability):

        self.capabilities[capability.id] = capability

    def get(self, capability_id):

        return self.capabilities.get(capability_id)

    def all(self):

        return list(self.capabilities.values())

    def enabled(self):

        return [
            c
            for c in self.capabilities.values()
            if c.enabled
        ]

    def active(self):
        if self.store is not None:
            rows = self.store.snapshot().get("autonomous_research", {}).get("capabilities", [])
            return [row for row in rows if self._selectable(row)]
        return [c for c in self.enabled() if c.status == "ACTIVE_CAPABILITY" and c.available]

    @staticmethod
    def _selectable(row, required_capability=None):
        if isinstance(row, Capability):
            values = {row.id, row.category, *(row.metadata.get("provides_capabilities") or [])}
            return bool(row.enabled and row.status == "ACTIVE_CAPABILITY" and row.available
                        and (required_capability is None or required_capability in values))
        values = {row.get("capability_id"), row.get("category"), *(row.get("provides_capabilities") or [])}
        try:
            verified_at = datetime.fromisoformat(str(row.get("last_verified_at", "")).replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - verified_at.astimezone(timezone.utc)
            verified = row.get("verification_valid", True) and age.total_seconds() <= Settings.CAPABILITY_VERIFICATION_MAX_AGE_SECONDS
        except (TypeError, ValueError):
            verified = False
        return bool(row.get("status") == "ACTIVE_CAPABILITY" and row.get("available")
                    and not row.get("disabled") and verified and not row.get("requires_approval")
                    and (required_capability is None or required_capability in values))

    def select(self, required_capability):
        """Availability signal only; this does not invoke a tool or grant side-effect permission."""
        return [row for row in self.active() if self._selectable(row, required_capability)]

    def invoke(self, capability_id: str, operation: Callable[[], object]):
        """Run an already-authorized invocation and record only the real outcome."""
        candidates = [row for row in self.active()
                      if (row.id if isinstance(row, Capability) else row.get("capability_id")) == capability_id]
        if not candidates:
            raise RuntimeError("Capability unavailable or approval required")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            result = operation()
        except Exception:
            self._record(capability_id, False, now)
            raise
        self._record(capability_id, True, now)
        return result

    def _record(self, capability_id: str, success: bool, now: str) -> None:
        if self.store is not None:
            def mutate(state):
                rows = state["autonomous_research"]["capabilities"]
                row = next(item for item in rows if item.get("capability_id") == capability_id)
                key = "success_count" if success else "failure_count"
                row[key] = int(row.get(key, 0)) + 1
                row["last_used_at"] = now
                tool = next((item for item in state["autonomous_research"]["tools"]
                             if item.get("capability_id") == capability_id), None)
                if tool is not None: tool.update({key: row[key], "last_used_at": now})
            self.store.update(mutate)
            return
        row = self.capabilities[capability_id]
        if success: row.success_count += 1
        else: row.failure_count += 1
        row.last_used_at = now

    def disable(self, capability_id):

        if capability_id in self.capabilities:

            self.capabilities[capability_id].enabled = False

    def enable(self, capability_id):

        if capability_id in self.capabilities:

            self.capabilities[capability_id].enabled = True
