from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from src.providers.execution_history import ProviderExecutionHistory


_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|password|passwd|secret|cookie|access[_-]?token|refresh[_-]?token)", re.I)
_SECRET_TEXT = re.compile(
    r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+|((?:api[_-]?key|password|secret|token)\s*[:=]\s*)[^\s,;]+"
)


def sanitize(value: Any) -> Any:
    """Return JSON-safe operational data without credential material."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return _SECRET_TEXT.sub(lambda match: (match.group(1) or match.group(2)) + "[REDACTED]", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None


def _duration(start: Any, finish: Any) -> float | None:
    try:
        start_dt = start if isinstance(start, datetime) else datetime.fromisoformat(str(start))
        end_dt = finish if isinstance(finish, datetime) else datetime.fromisoformat(str(finish))
        return round((end_dt - start_dt).total_seconds(), 3)
    except (TypeError, ValueError):
        return None


class ControlCenterReadModel:
    """Read-only projection over the existing runtime, store and provider history."""

    def __init__(self, service: Any) -> None:
        self.service = service

    @property
    def state(self) -> dict[str, Any]:
        return self.service.store.snapshot()

    def tasks(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        mission = getattr(getattr(self.service.runtime, "jarvis", None), "last_mission", None)
        for task in getattr(mission, "tasks", []) or []:
            task_metadata = getattr(task, "metadata", {}) or {}
            provider = task_metadata.get("preferred_ai_provider")
            row = {
                "id": task.id, "name": task.title, "department": task.agent or None,
                "worker": task.agent or None, "status": getattr(task.status, "value", str(task.status)),
                "started_at": _iso(task.started_at), "finished_at": _iso(task.finished_at),
                "duration_seconds": _duration(task.started_at, task.finished_at),
                "provider": provider, "error": sanitize(task.error) if task.error else None,
                "source": "mission_task",
            }
            # Mode B (Claude Code repo-edit delegation): CodingAgent writes
            # these keys into task.metadata (see
            # src/agents/coding_agent.py::_execute_repo_edit ->
            # ClaudeCodeEditOutcome.to_dict()) -- surfaced here read-only,
            # same sanitize()-wrapped pattern as every other field above.
            if task_metadata.get("delegated_to"):
                row.update({
                    "delegated_to": task_metadata.get("delegated_to"),
                    "files_changed": sanitize(task_metadata.get("files_changed", [])),
                    "files_changed_count": task_metadata.get("files_changed_count", 0),
                    "tests_executed": task_metadata.get("tests_executed", False),
                    "result_summary": sanitize(task_metadata.get("result_summary")),
                    "error_summary": sanitize(task_metadata.get("error_summary")),
                    "approval_required": task_metadata.get("approval_required", False),
                })
            rows.append(row)
        seen = {row["id"] for row in rows}
        for item in reversed(self.state.get("missions", [])):
            if item.get("id") in seen:
                continue
            rows.append({
                "id": item.get("id"), "name": item.get("goal") or "İsimsiz görev",
                "department": ", ".join(item.get("departments", [])) or None,
                "worker": item.get("worker") or None, "status": str(item.get("status", "queued")).lower(),
                "started_at": item.get("started_at"), "finished_at": item.get("finished_at"),
                "duration_seconds": _duration(item.get("started_at"), item.get("finished_at")),
                "provider": item.get("provider"), "error": sanitize(item.get("error")) if item.get("error") else None,
                "source": "mission",
            })
        return rows[:250]

    def workers(self) -> list[dict[str, Any]]:
        orchestrator = self.service.runtime.jarvis.ceo.department_orchestrator
        agents = getattr(orchestrator.adapters, "_agents", {})
        active = self.service._active or {}
        history = ProviderExecutionHistory().recent(500)
        last_by_type = {}
        for entry in history:
            last_by_type.setdefault(entry.get("task_type"), entry)
        rows = []
        for department, agent in agents.items():
            recent = last_by_type.get(department)
            is_active = active and department in active.get("departments", [])
            rows.append({
                "id": department, "name": type(agent).__name__, "department": department,
                "worker_id": department, "division": department.upper(), "role": type(agent).__name__,
                "status": "working" if is_active else "idle", "current_task": active.get("goal") if is_active else None,
                "provider": recent.get("provider") if recent else None, "model": None,
                "last_run_at": recent.get("recorded_at") if recent else None,
                "last_success": recent.get("success") if recent else None,
                "capabilities": [department], "capability_access": [department], "progress": active.get("progress", 0) if is_active else 0,
                "needs_approval": False, "last_result": None, "schedule": {},
            })
        return rows

    def providers(self) -> list[dict[str, Any]]:
        manager = self.service.runtime.jarvis.ceo.provider_manager
        entries = ProviderExecutionHistory().recent(500)
        rows = []
        for name in manager.names():
            matching = [entry for entry in entries if entry.get("provider") == name]
            durations = [float(entry["duration_seconds"]) for entry in matching if isinstance(entry.get("duration_seconds"), (int, float))]
            resource = next((entry.get("resource_type") for entry in matching if entry.get("resource_type")), None)
            provider = manager.get(name)
            rows.append({
                "name": name, "available": bool(provider and provider.is_available()),
                "success_rate": (round(100 * sum(bool(entry.get("success")) for entry in matching) / len(matching), 1)
                                 if matching else None),
                "resource_type": resource or getattr(provider, "resource_type", None),
                "last_used_at": matching[0].get("recorded_at") if matching else None,
                "successful_calls": sum(bool(entry.get("success")) for entry in matching),
                "failed_calls": sum(not bool(entry.get("success")) for entry in matching),
                "average_duration_seconds": round(sum(durations) / len(durations), 3) if durations else None,
                "fallback_count": sum(bool(entry.get("fallback_used")) for entry in matching),
                "task_types": dict(Counter(str(entry.get("task_type")) for entry in matching if entry.get("task_type"))),
            })
        return rows

    def approvals(self) -> list[dict[str, Any]]:
        allowed = {"id", "type", "status", "what", "why", "risk", "mission_id", "worker_id", "created_at", "decided_at", "decision_reason"}
        return [sanitize({key: value for key, value in item.items() if key in allowed}) for item in reversed(self.state.get("approvals", []))]

    def costs(self) -> dict[str, Any]:
        entries = ProviderExecutionHistory().recent(500)
        tracked = [entry for entry in entries if isinstance(entry.get("cost"), (int, float))]
        if not tracked:
            return {"available": False, "message": "Maliyet verisi henüz hesaplanmıyor.", "currency": None,
                    "today": None, "last_7_days": None, "by_provider": {}, "by_department": {}}
        now = datetime.now(timezone.utc)
        by_provider: defaultdict[str, float] = defaultdict(float)
        by_department: defaultdict[str, float] = defaultdict(float)
        today = week = 0.0
        for entry in tracked:
            cost = float(entry["cost"]); by_provider[str(entry.get("provider", "unknown"))] += cost
            by_department[str(entry.get("task_type", "unknown"))] += cost
            try:
                when = datetime.fromisoformat(str(entry.get("recorded_at"))).astimezone(timezone.utc)
                if when.date() == now.date(): today += cost
                if (now - when).days < 7: week += cost
            except ValueError: pass
        return {"available": True, "currency": "USD", "today": today, "last_7_days": week,
                "by_provider": dict(by_provider), "by_department": dict(by_department)}

    def youtube(self) -> dict[str, Any]:
        state = self.state
        accounts = self.service.accounts.redacted_accounts()
        connected = any(item.get("connection_status") == "CONNECTED" for item in accounts)
        supported = set(self.service.runtime.jarvis.ceo.department_orchestrator.adapters._agents)
        stages = [("Research", "research"), ("Topic Selection", None), ("Script", "media"),
                  ("Voice", "media"), ("Media", "media"), ("Editing", "media"),
                  ("Thumbnail", "media"), ("Quality Control", "media"),
                  ("Approval", None), ("Publish", None)]
        return {"connected": connected, "status": "CONNECTED" if connected else "NOT CONNECTED",
                "channels": accounts, "queue": state.get("engines", {}).get("youtube", {}).get("queue", []),
                "productions": state.get("youtube_learning", {}).get("productions", []),
                "pipeline": [{"name": label, "implementation": "implemented" if key in supported else "planned"}
                             for label, key in stages], "analytics": state.get("youtube_learning", {}).get("analytics", {"source": "NOT_CONNECTED", "records": []})}

    def finance(self) -> dict[str, Any]:
        state = self.state
        paper = state.get("paper", {})
        return {"mode": "PAPER / SIMULATION", "live_execution": False,
                "workers": [row for row in self.workers() if row["department"] in {"finance", "learning"}],
                "watchlist": state.get("engines", {}).get("finance", {}).get("watchlist", []),
                "paper_positions": paper.get("positions", []), "decision_history": state.get("finance_exploration", {}).get("runs", []),
                "has_real_portfolio": False}

    def research(self) -> dict[str, Any]:
        tasks = [row for row in self.tasks() if "research" in str(row.get("department", "")).lower()]
        return {"active": [row for row in tasks if row["status"] in {"running", "in_progress"}],
                "completed": [row for row in tasks if row["status"] == "completed"], "items": tasks}

    def logs(self) -> list[dict[str, Any]]:
        rows = [{"timestamp": row.get("time"), "severity": row.get("level", "info"),
                 "component": row.get("stage", "runtime"), "event": row.get("message"),
                 "task_id": row.get("mission_id"), "provider": row.get("worker") or None} for row in self.service._activities]
        audit = getattr(self.service.runtime.jarvis.ceo.audit, "logs", [])
        rows.extend({"timestamp": _iso(row.get("time")), "severity": "info", "component": row.get("action"),
                     "event": row.get("detail"), "task_id": None, "provider": None} for row in audit)
        return sanitize(list(reversed(rows[-300:])))

    def dashboard(self) -> dict[str, Any]:
        tasks = self.tasks(); workers = self.workers(); approvals = self.approvals(); providers = self.providers()
        counts = Counter(row["status"] for row in tasks)
        unavailable = sum(not row["available"] for row in providers)
        runtime_state = self.service.runtime.state
        status = "OFFLINE" if runtime_state == "STOPPED" else "DEGRADED" if unavailable or self.service.runtime.last_error else "ONLINE"
        return {"system_status": status, "runtime_state": runtime_state,
                "metrics": {"active_workers": sum(row["status"] == "working" for row in workers),
                            "running_tasks": counts["running"] + counts["in_progress"],
                            "completed_tasks": counts["completed"], "failed_tasks": counts["failed"] + counts["blocked"],
                            "pending_approvals": sum(row.get("status") == "PENDING" for row in approvals),
                            "active_departments": len({row["department"] for row in workers if row["status"] == "working"})},
                "provider_health": {"total": len(providers), "available": len(providers) - unavailable, "unavailable": unavailable},
                "recent_events": self.logs()[:10], "usage": {"records": len(ProviderExecutionHistory().recent(500))},
                "costs": self.costs()}
