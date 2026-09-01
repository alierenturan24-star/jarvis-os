from __future__ import annotations

import io
import json
import mimetypes
import os
import threading
import traceback
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.control_center.finance_engine import FinancePaperEngine
from src.control_center.observability import ControlCenterReadModel
from src.control_center.store import ControlCenterStore, utc_now
from src.core.runtime import JarvisRuntime
from src.media.channel_store import ChannelScopedStore
from src.media.learning import YouTubeLearningAgent
from src.media.quality import validate_media_goal_artifact
from src.providers.execution_history import ProviderExecutionHistory
from src.research_loop.autonomous import AutonomousResearchService
from src.capabilities.capability_registry import CapabilityRegistry
from src.capabilities.capability_manager import CapabilityManager
from src.capabilities.capability_evaluator import RepositoryEvidence, local_environment
from src.capabilities.repository_evidence import (
    RepositoryEvidenceAcquirer, RepositoryEvidenceAcquisitionError, MAX_CLAIMED_ENTRY_FILES)
from src.capabilities.sandbox_executor import CapabilitySandboxExecutor
from src.capabilities.capability_installer import ControlledCapabilityInstaller
from src.capabilities.integration_lifecycle import IntegrationLifecycleManager, local_environment_probe
from src.capabilities.build_delegation import delegate_capability_build
from src.jobs.job_manager import JobManager
from src.workforce import AccountConnectionManager, WorkforceManager, YouTubePublisher
from src.workforce.manager import ensure_channel_tag
from src.workforce.publisher import artifact_id


STAGE_NAMES = {"UNDERSTANDING", "PLANNING", "RESEARCH", "GITHUB", "BROWSER", "EVALUATION", "SANDBOX",
               "INTEGRATION", "PROVIDER", "MEDIA", "AUTOMATION", "FINANCE", "RECOVERY", "VALIDATION",
               "COMPLETED", "BLOCKED", "CODING", "AI_DISCOVERY"}


class CapabilityCandidateNotFound(LookupError):
    pass


class _ActivityWriter(io.TextIOBase):
    def __init__(self, service: "ControlCenterService") -> None:
        self.service, self.buffer = service, ""

    def write(self, value: str) -> int:
        self.buffer += value
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self.service.capture_runtime_line(line.strip())
        return len(value)


class ControlCenterService:
    """A management/observation adapter over the one real JarvisRuntime."""

    def __init__(self, runtime: JarvisRuntime | None = None, store: ControlCenterStore | None = None) -> None:
        self.runtime = runtime or JarvisRuntime()
        self.store = store or ControlCenterStore()
        self.finance = FinancePaperEngine(self.store)
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._active: dict[str, Any] | None = None
        self._activities: list[dict[str, Any]] = []
        self._paused = False
        self._provider_health: dict[str, bool] = {}
        self._started_at = utc_now()
        self._interrupted = self.store.recover_interrupted()
        self.workforce = WorkforceManager(self.store, notifier=self.notify)
        self.accounts = AccountConnectionManager(self.store)
        self.publisher = YouTubePublisher(self.store, self.accounts)
        self.autonomous_research = AutonomousResearchService(self.store)
        self.capability_registry = CapabilityRegistry(self.store)
        self.capability_manager = CapabilityManager(self.store)
        self.integration_lifecycle = IntegrationLifecycleManager(self.store)
        self.controlled_integration_executor = ControlledCapabilityInstaller()
        self.repository_evidence_acquirer = RepositoryEvidenceAcquirer()
        self.capability_sandbox_executor = CapabilitySandboxExecutor()
        mission_engine = getattr(getattr(getattr(self.runtime, "jarvis", None), "ceo", None), "mission_engine", None)
        if mission_engine is not None:
            mission_engine.capability_registry = self.capability_registry
        self._missed_workers = self.workforce.evaluate_missed_schedules()
        if self.runtime.state == self.runtime.BOOTING:
            self.runtime.boot()
        self.read_model = ControlCenterReadModel(self)

    def activity(self, stage: str, message: str, *, worker: str = "", level: str = "info",
                 mission_id: str | None = None) -> None:
        with self._lock:
            # Default to the currently-running mission so every activity/log
            # line emitted during its execution (including the ones parsed
            # from redirected stdout via capture_runtime_line) is traceable
            # back to it, without having to thread mission_id through every
            # call site individually.
            resolved_mission_id = mission_id if mission_id is not None else (
                self._active.get("id") if self._active else None)
            self._activities.append({"id": uuid.uuid4().hex, "time": utc_now(), "stage": stage,
                                     "message": message[:1000], "worker": worker, "level": level,
                                     "mission_id": resolved_mission_id})
            self._activities = self._activities[-300:]
            if self._active:
                self._active["stage"] = stage
                if worker: self._active["worker"] = worker

    def capture_runtime_line(self, line: str) -> None:
        stage, worker = "WORKING", ""
        if line.startswith("[A") and ":" in line:
            candidate = line.split(":", 1)[1].split("]", 1)[0].strip().upper()
            stage = candidate if candidate in STAGE_NAMES else "WORKING"
            if stage == "PROVIDER":
                worker = line.split("]", 1)[-1].strip()
        elif line.startswith("[") and "]" in line:
            worker = line[1:line.index("]")]
        self.activity(stage, line, worker=worker)

    @property
    def busy(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # JARVIS PRIORITY (Control Center explicit delegation hints, minimum
    # safe fix): the ONLY execution hints ``/api/command`` may ever inject
    # into a mission/task. Extending this requires the same deliberate
    # threading through ``Mission.execution_hints`` -> ``department_
    # orchestrator.create_tasks`` -- never a silent client-metadata passthrough.
    _CODING_MODE_ALLOWLIST = frozenset({"repo_edit"})

    def _validate_execution_hints(self, hints: Any) -> dict[str, str]:
        """Returns a NEW dict containing only recognized, validated keys --
        arbitrary client-supplied fields are always dropped, never copied
        through. Unknown/invalid values for a recognized key are silently
        DROPPED (not an error): for ``preferred_ai_provider`` this matches
        the existing ``ProviderManager.route_and_generate(preferred_provider=
        ...)`` precedent (falls back to normal automatic routing); for
        ``coding_mode`` dropping an unrecognized value means the task simply
        runs on the ordinary advisory (non-edit) path -- the safe default --
        so an unrecognized mode can never grant edit capability (fail
        closed toward the non-edit state, never toward an error)."""

        cleaned: dict[str, str] = {}
        if not isinstance(hints, dict):
            return cleaned

        provider = hints.get("preferred_ai_provider")
        if isinstance(provider, str) and provider.strip():
            manager = getattr(getattr(getattr(self.runtime, "jarvis", None), "ceo", None), "provider_manager", None)
            if manager is not None:
                normalized = manager.normalize(provider)
                if normalized in manager.names():
                    cleaned["preferred_ai_provider"] = normalized

        coding_mode = hints.get("coding_mode")
        if isinstance(coding_mode, str) and coding_mode in self._CODING_MODE_ALLOWLIST:
            cleaned["coding_mode"] = coding_mode

        return cleaned

    def submit_command(
        self, goal: str, source: str = "text", execution_hints: dict | None = None,
    ) -> dict[str, Any]:
        goal = " ".join((goal or "").split())
        if not goal:
            raise ValueError("Goal boş olamaz.")
        if len(goal) > 4000:
            raise ValueError("Goal 4000 karakteri aşamaz.")
        validated_hints = self._validate_execution_hints(execution_hints)
        with self._lock:
            if self.runtime.state == self.runtime.STOPPED:
                raise RuntimeError("JARVIS stopped; önce START gerekli.")
            if self._paused:
                raise RuntimeError("JARVIS paused; önce START/RESUME gerekli.")
            if self.busy:
                raise RuntimeError("Bir mission zaten çalışıyor.")
            mission = {"id": uuid.uuid4().hex, "goal": goal, "source": source, "status": "QUEUED",
                       "stage": "UNDERSTANDING", "worker": "", "progress": 0, "created_at": utc_now()}
            self._active = mission
            self.store.append("missions", dict(mission))
            self._thread = threading.Thread(
                target=self._run_command, args=(mission, validated_hints), daemon=True, name="jarvis-mission",
            )
            self._thread.start()
            return dict(mission)

    def _run_command(self, record: dict[str, Any], execution_hints: dict | None = None) -> None:
        record.update(status="WORKING", started_at=utc_now(), progress=5)
        self._persist_mission(record)
        self.activity("UNDERSTANDING", "Goal gerçek JARVIS pipeline'ına gönderildi.")
        try:
            with redirect_stdout(_ActivityWriter(self)):
                result = self.runtime.execute(record["goal"], execution_hints=execution_hints)
            if self.runtime.last_error is not None:
                detail = self.runtime.last_error_context or self.runtime.last_error
                raise RuntimeError(f"Runtime execution failed: {self.runtime.last_error}\n{detail}")
            mission = getattr(self.runtime.jarvis, "last_mission", None)
            provider_route = getattr(self.runtime.jarvis, "last_provider_route", None)
            status = getattr(getattr(mission, "status", None), "value", None) or "completed"
            record.update(status=status.upper(), stage="COMPLETED" if status == "completed" else "BLOCKED",
                          progress=float(getattr(mission, "progress", 100 if status == "completed" else 0)),
                          result=result, finished_at=utc_now(), departments=list(getattr(mission, "departments", [])),
                          artifacts=list(getattr(mission, "artifact_paths", [])))
            if provider_route is not None:
                record["provider_route"] = {
                    "chosen_provider": provider_route.chosen_provider,
                    "provider_used": provider_route.provider_used,
                    "fallback_used": provider_route.fallback_used,
                    "success": provider_route.success,
                    "reason": provider_route.reason,
                    "attempted_providers": list(getattr(provider_route, "attempted_providers", ())),
                }
            # Plain chat/provider work intentionally has no Mission object.
            # Domain evidence only exists for the CEO/MissionEngine path; do
            # not reinterpret a successful legacy result as mission metadata.
            if mission is not None:
                from src.mission.completion import domain_completion
                record["domain_progress"] = domain_completion(mission)
            else:
                record["domain_progress"] = {}
            self.activity(record["stage"], f"Mission {status}.", level="success" if status == "completed" else "warning")
            if record.get("artifacts"):
                media_task = next((task for task in getattr(mission, "tasks", []) if task.agent == "media"), None)
                production = media_task.metadata.get("youtube_production", {}) if media_task else {}
                quality = production.get("quality", {})
                self.notify("VIDEO READY", (
                    f"Quality: {quality.get('overall', '?')}/100 · Motion: "
                    f"{'PASS' if quality.get('motion', 0) >= 60 else 'FAIL'} · Story: "
                    f"{'PASS' if quality.get('story', 0) >= 80 else 'FAIL'} · Audio: "
                    f"{'PASS' if quality.get('audio', 0) >= 60 else 'FAIL'} · Learning: persisted"
                ), record["id"])
            finance_task = next((task for task in getattr(mission, "tasks", []) if task.agent == "finance"), None)
            finance_report = finance_task.metadata.get("report", {}) if finance_task is not None else {}
            lab = finance_report.get("strategy_lab", {}) if isinstance(finance_report, dict) else {}
            if lab.get("paper_promoted"):
                self.notify("FINANCE OPPORTUNITY", f"PAPER candidate: {lab.get('best_candidate')}", record["id"])
            if str(record.get("source", "")).startswith("worker:"):
                self._complete_worker_run(record, mission)
            recovery = getattr(mission, "recovery", None)
            for item in getattr(recovery, "approval_required", []) if recovery else []:
                task = next((task for task in mission.tasks if task.id == item.get("task_id")), None)
                paid_media = bool(task and task.agent == "media"
                                  and (task.metadata or {}).get("approval_action") == "paid_media_generation")
                details = ({**item, "action": "paid_media_generation",
                    "provider_candidates": list(task.metadata.get("approval_provider_candidates", [])),
                    "checkpoint_id": f"{mission.id}:{item.get('task_id', '')}"} if paid_media else item)
                self.create_approval("mission_capability", details,
                                     mission_id=mission.id if paid_media else record["id"])
            self.notify("MISSION COMPLETED" if status == "completed" else "MISSION BLOCKED", record["goal"], record["id"])
        except BaseException as error:
            # BaseException (not Exception): a runtime/provider escape (e.g. a
            # driver crash surfacing as SystemExit/CancelledError) must still
            # fail the mission closed. Catching only Exception here left a
            # documented live incident with status stuck WORKING and
            # error=null forever, because neither this handler nor the
            # success path ever ran.
            error_context = traceback.format_exc()
            record.update(status="BLOCKED", stage="BLOCKED", error=str(error),
                          error_context=error_context, finished_at=utc_now())
            self.activity("BLOCKED", error_context, level="error")
            self.notify("SYSTEM ERROR", str(error), record["id"])
            if str(record.get("source", "")).startswith("worker:"):
                # _complete_worker_run() (which would otherwise transition the
                # worker) only runs on the success path above -- without this,
                # a mission-level exception left the workforce worker stuck
                # reporting WORKING/progress=10 indefinitely even though its
                # own mission had already failed closed.
                worker_id = record["source"].split(":", 1)[1]
                try:
                    worker = self.workforce.worker(worker_id)
                    self.workforce.set_status(worker_id, "BLOCKED", last_error=str(error),
                                              last_result="BLOCKED", progress=record.get("progress", 0))
                    self.notify("WORKER BLOCKED", f"{worker['name']}: {error}", record["id"])
                except Exception:
                    pass
        finally:
            self._persist_mission(record)
            with self._lock: self._active = None

    def _persist_mission(self, record: dict[str, Any]) -> None:
        def mutate(state: dict[str, Any]) -> None:
            rows = state.setdefault("missions", [])
            existing = next((item for item in rows if item.get("id") == record.get("id")), None)
            if existing is None: rows.append(dict(record))
            else: existing.update(dict(record))
            del rows[:-250]
        self.store.update(mutate)

    def start(self) -> None:
        with self._lock:
            if self.runtime.state == self.runtime.STOPPED:
                self.runtime = JarvisRuntime(); self.runtime.boot()
            self._paused = False
        self.activity("COMPLETED", "Control Center START: configured engines may accept work.")

    def pause(self) -> None:
        self._paused = True
        self.activity("BLOCKED", "Yeni mission kabulü duraklatıldı; çalışan mission zorla kesilmedi.", level="warning")

    def stop(self, emergency: bool = False) -> None:
        self._paused = True
        self.runtime.shutdown()
        self.activity("BLOCKED", "EMERGENCY STOP" if emergency else "JARVIS stopped", level="error" if emergency else "warning")

    def create_approval(self, kind: str, details: dict[str, Any], mission_id: str = "") -> dict[str, Any]:
        action, task_id = details.get("action"), details.get("task_id")
        existing = next((row for row in self.store.snapshot().get("approvals", [])
                         if row.get("mission_id") == mission_id and row.get("task_id") == task_id
                         and row.get("action") == action and row.get("status") == "PENDING"), None) if action and task_id else None
        if existing is not None:
            return existing
        item = {"id": uuid.uuid4().hex, "type": kind, "status": "PENDING", "what": details.get("need", kind),
                "why": details.get("why", "Policy approval required"), "risk": details.get("risk", "HIGH"),
                "cost": details.get("cost"), "expected_result": details.get("expected_result"),
                "alternatives": details.get("alternatives", ["Reject and continue safe alternatives"]),
                "details": details, "mission_id": mission_id, "worker_id": details.get("worker_id"),
                "task_id": task_id, "action": action,
                "provider_candidates": details.get("provider_candidates", []),
                "checkpoint_id": details.get("checkpoint_id", ""),
                "created_at": utc_now()}
        self.store.append("approvals", item); self.notify("APPROVAL REQUIRED", item["what"], mission_id)
        return item

    def decide_approval(self, approval_id: str, approved: bool | None, reason: str = "") -> dict[str, Any]:
        found: dict[str, Any] = {}
        def mutate(state: dict[str, Any]) -> None:
            for item in state["approvals"]:
                if item.get("id") == approval_id and item.get("status") == "PENDING":
                    item.update(status="APPROVED" if approved is True else "CHANGES_REQUESTED" if approved is None else "REJECTED", decided_at=utc_now(),
                                decision_reason=(reason or "No additional reason supplied")[:1000],
                                decision_source="authenticated_control_center")
                    binding = item.get("binding", {})
                    if item.get("type") == "capability_proposal":
                        proposal = next((row for row in state["autonomous_research"]["proposals"]
                                         if row.get("proposal_id") == binding.get("proposal_id")
                                         and row.get("capability_id") == binding.get("capability_id")
                                         and row.get("approval_id") == approval_id), None)
                        if proposal is None: raise RuntimeError("CAPABILITY_APPROVAL_BINDING_MISMATCH")
                        proposal["status"] = ("APPROVED_PENDING_EXECUTOR" if approved is True else
                                              "CHANGES_REQUESTED" if approved is None else "REJECTED")
                        proposal["decided_at"] = item["decided_at"]
                        action = binding.get("requested_action")
                        event = ("INTEGRATION_APPROVED" if approved is True and action == "CONTROLLED_INTEGRATION" else
                                 "ACTIVATION_REJECTED" if approved is not True and action == "ACTIVATE_CAPABILITY" else None)
                        if event:
                            state["autonomous_research"]["capability_audit"].append({"time": utc_now(),
                                "capability_id": binding.get("capability_id"), "event": event,
                                "details": {"proposal_id": binding.get("proposal_id")}})
                    elif item.get("type") == "youtube_publish" and approved is not True:
                        # A rejected/changes-requested publish approval must retire the
                        # production_queue entry it created, or assert_youtube_capacity()
                        # sees it as forever-pending and the worker never becomes eligible
                        # for release below (nor for future capacity checks).
                        channel = state.get("channels", {}).get(binding.get("channel_id"))
                        if channel:
                            for prod in channel.get("production_queue", []):
                                if prod.get("approval_id") == approval_id:
                                    prod.update(status=item["status"], decided_at=item["decided_at"])
                    found.update(item); return
        self.store.update(mutate)
        if not found: raise KeyError("Pending approval bulunamadı.")
        # Approval is a decision record, never a direct execution endpoint.
        self.activity("VALIDATION", f"Approval {found['status']}: {found['what']}", level="warning")
        if found.get("type") == "youtube_publish" and approved is not True:
            # Release the worker from a stale WAITING_FOR_HUMAN/BACKLOG_LIMIT or
            # WAITING_APPROVAL now that this blocking decision is resolved, but only if
            # no other real pending production/approval remains for its channel.
            worker_id = found.get("worker_id") or found.get("binding", {}).get("worker_id")
            if worker_id:
                self.workforce.release_backlog_if_clear(worker_id)
        if found.get("type") == "youtube_publish" and approved is False:
            self._record_youtube_rejection_learning(found, reason)
        if found.get("type") == "mission_capability" and found.get("action") == "paid_media_generation" and approved is True:
            ceo = getattr(getattr(self.runtime, "jarvis", None), "ceo", None)
            if ceo is None:
                raise RuntimeError("Mission continuation unavailable")
            outcome = ceo.resume_paid_media_approval(found["mission_id"], found["task_id"])
            found["resume_result"] = outcome
            self.store.update(lambda state: next(row for row in state["approvals"]
                if row.get("id") == approval_id).update(resume_result=outcome))
        return found

    def _record_youtube_rejection_learning(self, approval: dict[str, Any], reason: str) -> None:
        """A human REJECTED an already-"QUALITY APPROVED" youtube_publish
        approval -- feed that back into the SAME channel-scoped learning
        memory ``MediaManager``/``GeneralProductionBuilder`` already read
        (``YouTubeLearningAgent.production_plan()``'s ``required_changes``),
        so the next production on this channel is warned. Reuses the exact
        record-keeping ``record_human_rejection`` already implements; this
        was previously never called on a real rejection (confirmed live:
        production 77b5c0b1e9c344d2ac1cbca052e85b7c's real REJECTED approval
        has no matching youtube_learning record at all). Defensive no-op if
        no learning record exists for the bound production -- an approval
        not tied to a tracked production must not raise.
        """
        binding = approval.get("binding", {})
        production_id = binding.get("production_id")
        channel_id = binding.get("channel_id")
        if not production_id or not channel_id:
            return
        agent = YouTubeLearningAgent(ChannelScopedStore(self.store, channel_id))
        try:
            agent.record_human_rejection(
                production_id,
                reasons=[reason or "human rejected via youtube_publish approval"],
                rejected_by="authenticated_control_center",
            )
        except KeyError:
            pass

    def begin_account_connection(self, worker_id: str, redirect_uri: str) -> dict:
        return self.accounts.begin(self.workforce.worker(worker_id), redirect_uri)

    def complete_account_connection(self, state: str, code: str) -> dict:
        result = self.accounts.provider.complete(state=state, code=code)
        channel = self.store.snapshot()["channels"][result["channel_id"]]
        return self.accounts.complete(result, market=channel["market"], language=channel["language"])

    def account_action(self, account_id: str, action: str) -> dict:
        if action == "verify": return self.accounts.verify(account_id)
        if action == "disconnect": return self.accounts.disconnect(account_id)
        raise ValueError("Unknown account action")

    def publisher_preflight(self, approval_id: str) -> dict:
        return self.publisher.publish(approval_id, execute=False)

    def test_notification(self) -> dict[str, Any]:
        item = {"id": uuid.uuid4().hex, "type": "SYSTEM TEST",
                "message": "Control Center notification delivery test; no credentials included.",
                "mission_id": "", "read": False, "created_at": utc_now()}
        self.store.append("notifications", item)
        return item

    def health(self) -> dict[str, Any]:
        state = self.store.snapshot()
        completed = [item for item in state.get("missions", []) if item.get("status") == "COMPLETED"]
        finance = state["engines"]["finance"]
        youtube = state["engines"]["youtube"]
        manager = getattr(getattr(getattr(self.runtime, "jarvis", None), "ceo", None), "provider_manager", None)
        provider_names = manager.names() if manager is not None else []
        runtime_started = getattr(self.runtime, "started_at", None)
        runtime_started_at = (
            runtime_started.astimezone().isoformat(timespec="seconds")
            if hasattr(runtime_started, "astimezone") else None
        )
        return {"backend_alive": True, "checked_at": utc_now(), "started_at": self._started_at,
                "process": {"pid": os.getpid(), "instance_id": self._started_at,
                            "runtime_started_at": runtime_started_at,
                            "build_identity": "jarvis-os-source"},
                "runtime_state": self.runtime.state, "finance": {"enabled": finance.get("enabled"),
                "mode": finance.get("mode"), "live_activation": False},
                "youtube": {"enabled": youtube.get("enabled"), "queued": sum(
                    item.get("status") == "QUEUED" for item in youtube.get("queue", []))},
                "provider_registry": {"registered": len(provider_names),
                                      "availability_probe": "on_demand",
                                      "availability": dict(self._provider_health)},
                "last_successful_mission": completed[-1].get("finished_at") if completed else None,
                "last_error": self.runtime.last_error,
                "notifications": {"persisted": True, "browser_delivery": "client_permission_required",
                                  "unread": sum(not item.get("read") for item in state.get("notifications", []))},
                "startup_recovered_interrupted": len(self._interrupted),
                "public_exposure": False}

    def mark_notifications_read(self) -> dict[str, Any]:
        return self.store.update(lambda s: [x.update(read=True, read_at=utc_now()) for x in s["notifications"] if not x.get("read")])

    def notify(self, kind: str, message: str, mission_id: str = "") -> None:
        self.store.append("notifications", {"id": uuid.uuid4().hex, "type": kind, "message": message[:500],
                                             "mission_id": mission_id, "read": False, "created_at": utc_now()})

    def enqueue_youtube(self, goal: str) -> dict[str, Any]:
        item = {"id": uuid.uuid4().hex, "goal": goal.strip(), "status": "QUEUED", "created_at": utc_now()}
        if not item["goal"]: raise ValueError("YouTube goal boş olamaz.")

        def mutate(s: dict[str, Any]) -> None:
            queue = s["engines"]["youtube"]["queue"]
            # Sprint: research/production pipeline audit -- a real Swiss
            # Insider run dispatched an OLDER, simpler goal while a NEWER,
            # more detailed one the user had since submitted sat still
            # QUEUED behind it (run_next_youtube() takes the first item
            # with status=="QUEUED" in insertion order). A fresh submission
            # is the user's current, authoritative intent for the NEXT
            # production -- supersede (never delete, for audit history) any
            # earlier still-QUEUED item so the queue can never dispatch a
            # stale goal instead of the one the user actually just asked
            # for. Dispatched/interrupted/completed items are untouched.
            for existing in queue:
                if existing.get("status") == "QUEUED":
                    existing.update(status="SUPERSEDED", superseded_at=utc_now(), superseded_by=item["id"])
            queue.append(item)

        self.store.update(mutate)
        return item

    def run_next_youtube(self) -> dict[str, Any]:
        state = self.store.snapshot(); queue = state["engines"]["youtube"]["queue"]
        item = next((x for x in queue if x["status"] == "QUEUED"), None)
        if not item: raise RuntimeError("YouTube production queue boş.")
        worker_id, channel_id = self._resolve_youtube_dispatch(item.get("channel_id"))
        # Resolution and run_worker_now's own capacity/enabled/submit checks all raise
        # before any mission is created, so a failed dispatch leaves the queue item QUEUED
        # (safe to retry/inspect) instead of stuck DISPATCHED with no mission behind it.
        mission = self.run_worker_now(worker_id, goal=item["goal"])
        self.store.update(lambda s: next(x for x in s["engines"]["youtube"]["queue"] if x["id"] == item["id"]).update(
            status="DISPATCHED", mission_id=mission["id"], worker_id=worker_id, channel_id=channel_id))
        return mission

    def _resolve_youtube_dispatch(self, channel_id: str | None) -> tuple[str, str]:
        """Resolve the YOUTUBE worker/channel for a queued goal from connected-account state.

        Never hardcodes a worker/channel id: it walks ``account_assignments`` (the same
        source of truth the OAuth connection flow writes to) so whichever channel is
        actually CONNECTED — Swiss Insider/sinem today, any other worker's channel
        tomorrow — is the one production dispatches to.
        """
        accounts = [a for a in self.store.snapshot().get("account_assignments", [])
                    if a.get("connection_status") == "CONNECTED" and (channel_id is None or a.get("channel_id") == channel_id)]
        if not accounts:
            raise RuntimeError("NO_CONNECTED_YOUTUBE_ACCOUNT" + (f" for channel {channel_id}" if channel_id else ""))
        if channel_id is None and len({a["channel_id"] for a in accounts}) > 1:
            raise RuntimeError("AMBIGUOUS_YOUTUBE_CHANNEL: multiple connected channels; specify channel_id")
        account = accounts[0]
        worker = self.workforce.worker(account["assigned_worker_id"])
        if worker["division"] != "YOUTUBE" or worker.get("channel_id") != account["channel_id"]:
            raise RuntimeError("ACCOUNT_WORKER_CHANNEL_MISMATCH")
        return worker["worker_id"], account["channel_id"]

    def run_worker_now(self, worker_id: str, *, scheduled_for: str | None = None, job_type: str | None = None,
                        goal: str | None = None) -> dict[str, Any]:
        worker = self.workforce.worker(worker_id)
        if not worker.get("enabled") or worker.get("status") == "PAUSED":
            raise RuntimeError("Worker paused/disabled")
        execution_id = self.workforce.claim_execution(worker_id, scheduled_for)
        if job_type == "PUBLICATION":
            raise RuntimeError("Scheduled publication requires a separately approved publication action")
        if worker["division"] == "YOUTUBE":
            capacity = self.workforce.assert_youtube_capacity(worker_id)
            resolved_goal = ensure_channel_tag(goal if goal is not None else self.workforce.youtube_goal(worker_id),
                                               worker["channel_id"])
            self.workforce.set_status(worker_id, "PLANNING", current_goal=resolved_goal,
                current_task="bounded opportunity and production", last_started_at=utc_now(), progress=5.0)
            self.workforce.decision(worker_id, goal=resolved_goal, decision="RUN PRODUCTION",
                why="Scheduled/run-now channel operation", evidence={"execution_id": execution_id,
                "analytics": worker["channel"]["youtube_learning"]["analytics"].get("status", "ANALYTICS INSUFFICIENT"),
                "capacity": capacity, "required_capabilities": worker["capability_access"]},
                # Sprint: capability-gate audit -- this decision fires at DISPATCH
                # time, before the media pipeline has run at all, so nothing has
                # actually been "used" yet. The full worker capability list used to
                # be declared here as capabilities_used, which is exactly the false
                # claim the audit found (mission 4a50230ffad2400bbb2aff173bd2a797:
                # RUN PRODUCTION declared character_visual_generation/motion_
                # generation/video_render "used" before any of them had run).
                # required_capabilities (above) records intent; capabilities_used
                # stays empty until something has genuinely executed.
                capabilities_used=[], risk="LOW",
                expected_result="Validated unpublished artifact queued for approval")
            try:
                mission = self.submit_command(resolved_goal, f"worker:{worker_id}")
            except Exception as error:
                # submit_command can reject (paused/stopped/busy) after PLANNING already
                # started; without this the worker would stay stuck at PLANNING with no
                # mission behind it instead of truthfully reporting the failure.
                self.workforce.set_status(worker_id, "BLOCKED", last_error=str(error), progress=0.0)
                self.notify("WORKER BLOCKED", f"{worker['name']}: {error}")
                raise
            self.workforce.set_status(worker_id, "WORKING", current_mission_id=mission["id"], progress=10.0)
            return {**mission, "worker_id": worker_id, "execution_id": execution_id}
        if worker_id == "eren":
            self.workforce.set_status("eren", "RESEARCHING", current_task="bounded strategy exploration",
                                      last_started_at=utc_now(), progress=10.0)
            try:
                lab = self.finance.explore_strategies("BTC", retest_reason="digital workforce run")
                self.workforce.set_status("eren", "IDLE", current_task="", last_completed_at=utc_now(),
                    last_result=f"{lab['strategy_count']} candidates; {lab['decision']}", progress=100.0)
                self.workforce.decision("eren", goal="Finance bounded exploration", decision="SUBMIT FOR INDEPENDENT REVIEW",
                    why="Exploration evidence completed; EREN cannot self-qualify", evidence={"strategy_lab_id": lab["id"]},
                    capabilities_used=worker["capability_access"], risk="PAPER_ONLY", expected_result="CEMO review",
                    actual_result=lab["decision"])
                return {"worker_id": "eren", "execution_id": execution_id, "strategy_lab": lab}
            except Exception as error:
                self.workforce.set_status("eren", "BLOCKED", last_error=str(error), progress=0.0)
                self.notify("WORKER BLOCKED", f"EREN: {error}")
                return {"worker_id": "eren", "execution_id": execution_id, "status": "BLOCKED", "error": str(error)}
        if worker_id == "cemo":
            labs = self.store.snapshot().get("strategy_labs", [])
            if not labs: raise RuntimeError("CEMO review için Strategy Lab evidence yok")
            self.workforce.set_status("cemo", "VALIDATING", current_task="independent finance qualification", progress=40.0)
            review = self.workforce.finance_review(labs[-1])
            self.workforce.set_status("cemo", "IDLE", current_task="", last_completed_at=utc_now(),
                last_result=review["decision"], progress=100.0)
            self.workforce.decision("cemo", goal="Independent finance review", decision=review["decision"],
                why="Independent evidence checks", evidence=review, capabilities_used=worker["capability_access"],
                risk="PAPER_ONLY", expected_result="QUALIFIED FOR PAPER or REJECTED", actual_result=review["decision"])
            return {"worker_id": "cemo", "execution_id": execution_id, "review": review}
        raise RuntimeError("Bu worker için RUN NOW operasyonu tanımlı değil")

    def scheduler_tick(self) -> list[dict]:
        results = []
        if self.busy or self._paused: return results
        for due in self.workforce.due_jobs():
            try:
                if due["job_type"] == "PUBLICATION":
                    self.workforce.claim_execution(due["worker_id"], due["scheduled_for"])
                    self.workforce.set_status(due["worker_id"], "WAITING_FOR_HUMAN",
                                              current_task="Publication schedule awaiting exact approval")
                    results.append({**due, "status": "WAITING_FOR_HUMAN"})
                elif due["job_type"] == "RESEARCH" and due["worker_id"] in {"deniz", "ceren", "sinem"}:
                    self.workforce.claim_execution(due["worker_id"], due["scheduled_for"])
                    self.workforce.decision(due["worker_id"], goal="Bounded market opportunity scan",
                        decision="RESEARCH SCHEDULE CHECKED", why="Research is separated from artifact production",
                        evidence={"trend_data": "UNAVAILABLE_UNLESS_PROVIDER_RETURNS_EVIDENCE"},
                        capabilities_used=["content_opportunity"], risk="LOW", expected_result="No large artifact backlog")
                    results.append({**due, "status": "RESEARCH_RECORDED"})
                else:
                    results.append(self.run_worker_now(due["worker_id"], scheduled_for=due["scheduled_for"],
                                                       job_type=due["job_type"]))
            except Exception as error:
                self.workforce.set_status(due["worker_id"], "RECOVERY_REQUIRED", last_error=str(error))
                results.append({**due, "status": "RECOVERY_REQUIRED", "error": str(error)})
            finally:
                self.workforce.advance_schedule(due["worker_id"])
            if self.busy: break
        if not self.busy and not self._paused:
            results.extend({"type": "AUTONOMOUS_RESEARCH", **row} for row in self.autonomous_research.run_due())
        return results

    def research_topics(self) -> list[dict[str, Any]]:
        return self.autonomous_research.topics()

    def create_research_topic(self, data: dict[str, Any]) -> dict[str, Any]:
        return self.autonomous_research.create_topic(str(data.get("name", "")), str(data.get("description", "")),
            enabled=data.get("enabled", True), priority=data.get("priority", 50),
            research_interval=data.get("research_interval", 86400),
            source_preferences=data.get("source_preferences", []), tags=data.get("tags", []))

    def research_state(self) -> dict[str, Any]:
        state = self.store.snapshot()["autonomous_research"]
        return {key: state[key] for key in ("topics", "cycles", "findings", "tools", "capabilities", "evaluations", "capability_audit", "proposals",
                                                  "integration_plans", "integration_verifications", "mission_continuations")}

    def evaluate_capability(self, capability_id: str) -> dict[str, Any]:
        candidate = next((row for row in self.store.snapshot()["autonomous_research"]["tools"]
                          if row.get("capability_id") == capability_id), None)
        if candidate is None:
            raise CapabilityCandidateNotFound("Capability candidate not found")
        source = candidate.get("source_evidence")
        if not isinstance(source, dict):
            source = {}
        repository_url = str(source.get("repository_url") or source.get("source_url") or
                             (f"https://github.com/{candidate['repository']}" if candidate.get("repository") else ""))
        if not self._repository_evidence_sufficient(source) and candidate.get("repository"):
            try:
                acquired = self.repository_evidence_acquirer.acquire(str(candidate["repository"]), repository_url)
                source = self._persist_repository_evidence(capability_id, acquired)
                repository_url = str(source.get("repository_url") or repository_url)
                self.capability_manager._audit(capability_id, "READ_ONLY_EVIDENCE_ACQUIRED", {
                    "items": len(source.get("evidence_items", [])), "trust_boundary": "UNTRUSTED_EXTERNAL_CONTENT"})
            except Exception as error:
                failure = {"acquisition_status": "FAILED", "error_type": type(error).__name__,
                           "error": str(error), "retrieved_at": utc_now(),
                           "trust_boundary": "UNTRUSTED_EXTERNAL_CONTENT"}
                source = self._persist_repository_evidence(capability_id, failure)
                self.capability_manager._audit(capability_id, "READ_ONLY_EVIDENCE_FAILED", failure)
        evidence = RepositoryEvidence(
            repository_url=repository_url,
            readme=str(source.get("readme") or source.get("readme_content") or ""),
            files=dict(source.get("files") or {}),
            metadata=dict(source.get("metadata") or {}),
            evidence_items=list(source.get("evidence_items") or []),
        )
        result = self.capability_manager.evaluate(capability_id, evidence, local_environment())
        proposal = next((row for row in reversed(self.store.snapshot()["autonomous_research"]["proposals"])
                         if row.get("capability_id") == capability_id
                         and row.get("requested_action") == "SANDBOX_VERIFICATION"), None)
        self._bind_capability_continuations(
            capability_id, "SANDBOX_APPROVAL_REQUIRED" if proposal else "EVALUATION_FAILED",
            proposal_id=str(proposal.get("proposal_id") or "") if proposal else "",
        )
        return result

    def execute_capability_proposal(self, proposal_id: str) -> dict[str, Any]:
        # ThreadingHTTPServer can receive duplicate clicks concurrently. Keep the
        # approval re-check and terminal persistence in one process-local section.
        with self._lock:
            proposals = self.store.snapshot()["autonomous_research"]["proposals"]
            if not any(row.get("proposal_id") == proposal_id for row in proposals):
                raise CapabilityCandidateNotFound("Capability proposal not found")
            outcome = self.capability_manager.execute_approved(proposal_id, self.capability_sandbox_executor)
            proposal = next(row for row in self.store.snapshot()["autonomous_research"]["proposals"]
                            if row.get("proposal_id") == proposal_id)
            self._bind_capability_continuations(
                str(proposal["capability_id"]),
                "SANDBOX_VERIFIED" if outcome.get("success") else "SANDBOX_FAILED",
                proposal_id=proposal_id,
            )
            return outcome

    def plan_capability_integration(self, capability_id: str) -> dict[str, Any]:
        if not any(x.get("capability_id") == capability_id for x in self.store.snapshot()["autonomous_research"]["tools"]):
            raise CapabilityCandidateNotFound("Capability candidate not found")
        plan = self.integration_lifecycle.plan(capability_id, local_environment_probe())
        proposal = next(row for row in reversed(self.store.snapshot()["autonomous_research"]["proposals"])
                        if row.get("capability_id") == capability_id
                        and row.get("requested_action") == "CONTROLLED_INTEGRATION")
        self._bind_capability_continuations(
            capability_id, "INTEGRATION_APPROVAL_REQUIRED", proposal_id=proposal["proposal_id"],
        )
        return plan

    def integration_plans(self) -> list[dict[str, Any]]:
        return self.store.snapshot()["autonomous_research"]["integration_plans"]

    def execute_integration_proposal(self, proposal_id: str) -> dict[str, Any]:
        if not any(x.get("proposal_id") == proposal_id for x in self.store.snapshot()["autonomous_research"]["proposals"]):
            raise CapabilityCandidateNotFound("Integration proposal not found")
        with self._lock:
            outcome = self.integration_lifecycle.execute_integration(proposal_id, self.controlled_integration_executor)
            proposal = next(row for row in self.store.snapshot()["autonomous_research"]["proposals"]
                            if row.get("proposal_id") == proposal_id)
            self._bind_capability_continuations(
                str(proposal["capability_id"]),
                "INTEGRATION_VERIFIED" if outcome.get("success") else "VERIFICATION_FAILED",
                proposal_id=proposal_id,
            )
            return outcome

    def propose_capability_build(self, capability_id: str, repo_path: str, *, run_tests: bool = True) -> dict[str, Any]:
        """Request the existing edit/test approvals for a bounded build task.

        Merely discovering or sandboxing a repository cannot call this path.
        The candidate must already have a current integration plan.
        """
        state = self.store.snapshot()["autonomous_research"]
        plan = next((row for row in state["integration_plans"]
                     if row.get("capability_id") == capability_id and row.get("current") is True), None)
        if plan is None:
            raise RuntimeError("Current integration plan required before coding delegation")
        return self.create_approval("capability_build", {
            "need": f"Bounded capability code integration: {capability_id}",
            "why": "Existing integration plan requires repository adapter/code work",
            "risk": "MEDIUM",
            "expected_result": "CODING_WORKER_REQUIRED",
            "requested_action": "edit_project_file",
            "capability_id": capability_id,
            "integration_plan_id": plan["integration_plan_id"],
            "repo_path": str(Path(repo_path).resolve()),
            "run_tests": bool(run_tests),
        })

    def execute_capability_build(self, approval_id: str, *, job_manager: JobManager | None = None,
                                 adapter_registry=None) -> dict[str, Any]:
        approval = next((row for row in self.store.snapshot()["approvals"]
                         if row.get("id") == approval_id), None)
        if approval is None or approval.get("type") != "capability_build" or approval.get("status") != "APPROVED":
            raise RuntimeError("Explicit capability-build approval required")
        details = approval.get("details") or {}
        if details.get("requested_action") != "edit_project_file":
            raise RuntimeError("Capability-build approval binding mismatch")
        plan = next((row for row in self.store.snapshot()["autonomous_research"]["integration_plans"]
                     if row.get("integration_plan_id") == details.get("integration_plan_id")
                     and row.get("capability_id") == details.get("capability_id")
                     and row.get("current") is True), None)
        if plan is None:
            raise RuntimeError("Current integration-plan binding required")
        task = delegate_capability_build(
            str(details["capability_id"]), str(details["repo_path"]), approved=True,
            run_tests=bool(details.get("run_tests", True)), adapter_registry=adapter_registry,
        )
        (job_manager or JobManager()).run_task(task)
        delegated_status = str(task.metadata.get("status") or "FAILED")
        if delegated_status == "FAILED" and "kullan" in str(task.result or task.error).casefold():
            delegated_status = "CODING_WORKER_UNAVAILABLE"
        self._bind_capability_continuations(str(details["capability_id"]), delegated_status)
        self.store.update(lambda state: next(row for row in state["approvals"]
                                             if row.get("id") == approval_id).update(status="EXECUTED"))
        # This result is evidence only. Integration verification and the
        # independent activation approval remain mandatory and untouched.
        return {"status": delegated_status, "task_id": task.id,
                "capability_id": details["capability_id"],
                "files_changed": list(task.metadata.get("files_changed") or []),
                "tests_executed": bool(task.metadata.get("tests_executed")),
                "approval_required": bool(task.metadata.get("approval_required")),
                "result": str(task.result.output if task.result is not None else task.error)}

    def propose_capability_activation(self, capability_id: str) -> dict[str, Any]:
        if not any(x.get("capability_id") == capability_id for x in self.store.snapshot()["autonomous_research"]["tools"]):
            raise CapabilityCandidateNotFound("Capability candidate not found")
        proposal = self.integration_lifecycle.propose_activation(capability_id)
        self._bind_capability_continuations(
            capability_id, "ACTIVATION_APPROVAL_REQUIRED", proposal_id=proposal["proposal_id"],
        )
        return proposal

    def execute_activation_proposal(self, proposal_id: str) -> dict[str, Any]:
        if not any(x.get("proposal_id") == proposal_id for x in self.store.snapshot()["autonomous_research"]["proposals"]):
            raise CapabilityCandidateNotFound("Activation proposal not found")
        with self._lock:
            capability = self.integration_lifecycle.activate(proposal_id)
            self._bind_capability_continuations(
                capability["capability_id"], "RESUME_READY", proposal_id=proposal_id,
            )
            ceo = getattr(getattr(self.runtime, "jarvis", None), "ceo", None)
            resume = ceo.resume_capability_continuations(capability["capability_id"]) if ceo is not None else []
            return {**capability, "mission_continuations": resume}

    def _bind_capability_continuations(self, capability_id: str, status: str, *, proposal_id: str = "") -> None:
        def mutate(state: dict[str, Any]) -> None:
            for row in state["autonomous_research"]["mission_continuations"]:
                if row.get("capability_id") != capability_id or row.get("status") in {"RESUMED", "RESUME_FAILED"}:
                    continue
                row["status"] = status
                if proposal_id:
                    row["proposal_id"] = proposal_id
                row["updated_at"] = utc_now()
        self.store.update(mutate)

    @staticmethod
    def _repository_evidence_sufficient(source: dict[str, Any]) -> bool:
        readme = str(source.get("readme") or source.get("readme_content") or "")
        if not readme or not (source.get("files") or source.get("metadata")):
            return False
        files = source.get("files") or {}
        claimed = RepositoryEvidenceAcquirer._claimed_python_paths(readme)[:MAX_CLAIMED_ENTRY_FILES]
        # A prior acquisition round can predate/miss the claimed-entry-file fetch (e.g. a
        # transient GitHub error on just those calls) and still look "sufficient" by
        # readme+files alone, permanently starving discover_runtime_interface() of the
        # structural proof it needs. Treat evidence missing a claimed entry file's content
        # as insufficient so the next evaluation retries acquisition for it.
        return all(path in files for path in claimed)

    def _persist_repository_evidence(self, capability_id: str, acquired: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        def mutate(state: dict[str, Any]) -> None:
            nonlocal result
            tool = next(row for row in state["autonomous_research"]["tools"] if row.get("capability_id") == capability_id)
            prior = tool.get("source_evidence") if isinstance(tool.get("source_evidence"), dict) else {}
            merged = {**prior, **acquired}
            existing = list(prior.get("evidence_items") or [])
            keys = {(x.get("evidence_type"), x.get("path"), x.get("content_sha256")) for x in existing}
            for item in acquired.get("evidence_items", []):
                key = (item.get("evidence_type"), item.get("path"), item.get("content_sha256"))
                if key not in keys: existing.append(item); keys.add(key)
            if existing: merged["evidence_items"] = existing
            tool["source_evidence"] = merged
            result = dict(merged)
        self.store.update(mutate)
        return result

    def _complete_worker_run(self, record: dict, mission) -> None:
        worker_id = record["source"].split(":", 1)[1]
        worker = self.workforce.worker(worker_id)
        media = next((task for task in mission.tasks if task.agent == "media"), None)
        capability_gap = media.metadata.get("capability_gap") if media else None
        production = media.metadata.get("youtube_production") if media else None
        if not production and capability_gap:
            # Sprint: capability-gate audit -- an honest CAPABILITY_GAP (no
            # genuine visual-generation capability for this goal) must be
            # recorded truthfully, never as an unlabeled generic BLOCKED, and
            # must never reach quality_review/youtube_publish approval below
            # (no artifact exists to review). Research/script evidence
            # already generated before the gap was found is untouched here --
            # MediaManager.plan() always persists its report before attempting
            # production, regardless of outcome.
            missing = capability_gap.get("missing_capabilities", [])
            self.workforce.decision(worker_id, goal=record["goal"], decision="CAPABILITY_GAP",
                why="No genuine visual-generation capability available for this goal; stopped before "
                    "rendering rather than substituting an unrelated/placeholder asset",
                evidence={"missing_capabilities": missing,
                          "available_capabilities": capability_gap.get("available_capabilities", []),
                          "required_capabilities": capability_gap.get("required_capabilities", []),
                          "requested_content_type": capability_gap.get("requested_content_type", "youtube_short"),
                          "channel_id": capability_gap.get("channel_id", worker.get("channel_id")),
                          "reason": capability_gap.get("reason", "CAPABILITY_GAP"),
                          "report_path": capability_gap.get("report_path", "")},
                capabilities_used=[], risk="LOW",
                expected_result="Honest CAPABILITY_GAP; no unrelated/placeholder asset substituted",
                actual_result="CAPABILITY_GAP")
            self.workforce.set_status(worker_id, "BLOCKED",
                last_error=f"CAPABILITY_GAP: missing {', '.join(missing) or 'visual generation'}",
                last_result="CAPABILITY_GAP", progress=record.get("progress", 0))
            self.notify("CAPABILITY GAP", f"{worker['name']}: {capability_gap.get('reason', 'CAPABILITY_GAP')}", record["id"])
            return
        if not production:
            self.workforce.set_status(worker_id, "BLOCKED", last_error="Production evidence missing",
                                      last_result="BLOCKED", progress=record.get("progress", 0))
            self.notify("WORKER BLOCKED", f"{worker['name']}: production evidence missing", record["id"])
            return
        self.workforce.set_status(worker_id, "VALIDATING", current_task="EYLEM independent quality review", progress=90.0)
        self.workforce.set_status("eylem", "VALIDATING", current_goal=record["goal"],
                                  current_mission_id=record["id"], current_task=f"Review {production['production_id']}", progress=50.0)
        channel = self.store.snapshot()["channels"][worker["channel_id"]]
        review = self.workforce.quality_review(production, channel)
        self.workforce.decision("eylem", goal=record["goal"], decision=review["decision"],
            why="Producer cannot self-approve", evidence=review, capabilities_used=self.workforce.worker("eylem")["capability_access"],
            risk="LOW", expected_result="Independent quality verdict", actual_result=review["decision"])
        self.workforce.set_status("eylem", "IDLE", current_task="", last_completed_at=utc_now(),
                                  last_result=review["decision"], progress=100.0)
        if review["passed"]:
            artifact_path = production["artifact"]["final_video_path"]
            account = self.accounts.account_for_channel(worker["channel_id"])
            binding = {"artifact_id": artifact_id(artifact_path), "artifact_path": artifact_path,
                "production_id": production["production_id"], "channel_id": worker["channel_id"],
                "artifact_channel_id": production.get("channel_id", worker["channel_id"]),
                "account_id": account.get("account_id") if account else "", "worker_id": worker_id}
            approval = self.create_approval("youtube_publish", {"worker_id": worker_id,
                "need": f"Publish {production['production_id']} to {worker['channel_id']}",
                "why": "V2 requires independent human approval bound to this exact artifact",
                "risk": "HIGH", "expected_result": "Separate credential-aware publication action",
                "binding": binding, "publication_metadata": {"title": production.get("title") or production.get("topic") or "Untitled",
                    "description": production.get("description", ""), "content_type": "SHORT",
                    "language": channel.get("language"), "privacy_status": "private"}}, record["id"])
            self.store.update(lambda s: (s["approvals"][-1].update(binding=binding,
                publication_metadata={"title": production.get("title") or production.get("topic") or "Untitled",
                    "description": production.get("description", ""), "content_type": "SHORT",
                    "language": channel.get("language"), "privacy_status": "private"}),
                s["channels"][worker["channel_id"]]["production_queue"].append({**binding,
                    "approval_id": approval["id"], "status": "READY_FOR_APPROVAL", "created_at": utc_now()})))
            self.workforce.set_status(worker_id, "WAITING_APPROVAL", current_task="human publish approval",
                last_completed_at=utc_now(), last_result="VIDEO READY — QUALITY APPROVED", progress=100.0,
                needs_approval=True, learning_refs=[production["production_id"]])
            self.notify("VIDEO READY", f"{worker['name']}: {production['production_id']} quality approved; publish not used", record["id"])
        else:
            self.workforce.set_status(worker_id, "RECOVERY_REQUIRED", last_error=", ".join(review["required_changes"]),
                                      last_result="QUALITY REJECTED", progress=90.0)

    def worker_control(self, worker_id: str, action: str, data: dict | None = None):
        if action == "pause": return self.workforce.pause(worker_id)
        if action == "resume": return self.workforce.resume(worker_id)
        if action == "disable": return self.workforce.disable(worker_id)
        if action == "run-now": return self.run_worker_now(worker_id)
        if action == "schedule": return self.workforce.change_schedule(worker_id, data or {})
        raise ValueError("Unknown worker control")

    def artifacts(self) -> list[dict[str, Any]]:
        root = Path("workspace").resolve(); values = []
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".mp4", ".md", ".json", ".png", ".jpg", ".wav", ".mp3"}: continue
            if any(part.startswith(".") for part in path.relative_to(root).parts): continue
            values.append({"path": path.relative_to(root).as_posix(), "name": path.name, "type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                           "size": path.stat().st_size, "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})
        return sorted(values, key=lambda x: x["modified"], reverse=True)[:200]

    def providers(self) -> list[dict[str, Any]]:
        from src.providers.cost_optimizer import CostOptimizer
        manager = self.runtime.jarvis.ceo.provider_manager
        history = ProviderExecutionHistory()
        rows = [{"name": name, "available": manager.get(name).is_available(),
                 "success_rate": history.success_rate(name),
                 "cost_class": CostOptimizer.cost_class(name)} for name in manager.names()]
        self._provider_health = {item["name"]: item["available"] for item in rows}
        return rows

    def snapshot(self) -> dict[str, Any]:
        persisted = self.store.snapshot()
        with self._lock: active, activities = dict(self._active) if self._active else None, list(reversed(self._activities[-80:]))
        return {"core": {"state": "BLOCKED" if self._paused else self.runtime.state, "busy": self.busy,
                          "completed_tasks": self.runtime.completed_tasks, "last_error": self.runtime.last_error,
                          "last_mission_status": self.runtime.last_mission_status}, "active_mission": active,
                "activities": activities, "missions": list(reversed(persisted["missions"][-50:])),
                "engines": persisted["engines"], "approvals": list(reversed(persisted["approvals"][-100:])),
                "notifications": list(reversed(persisted["notifications"][-50:])), "paper": persisted["paper"],
                "backtests": list(reversed(persisted["backtests"][-30:])),
                "finance_exploration": persisted.get("finance_exploration", {}),
                "youtube_learning": persisted.get("youtube_learning", {}),
                "workforce": {"workers": self.workforce.workers(),
                    "summary": self.workforce_summary(),
                    "decisions": list(reversed(persisted.get("workforce", {}).get("decisions", [])[-100:])),
                    "vault": {"backend": self.workforce.vault.backend, "available": self.workforce.vault.available,
                              "secrets_exposed": False}},
                "accounts": self.accounts.redacted_accounts(),
                "operations": self.workforce.operations_health(),
                "channels": persisted.get("channels", {}),
                "health": self.health(),
                "finance_performance": self.finance.performance(),
                "provider_history": ProviderExecutionHistory().recent(30)}

    def workforce_summary(self) -> dict[str, int]:
        workers = self.workforce.workers()
        return {"active": sum(w["status"] in {"RESEARCHING", "PLANNING", "WORKING", "VALIDATING"} for w in workers),
                "idle": sum(w["status"] == "IDLE" for w in workers),
                "blocked": sum(w["status"] in {"BLOCKED", "RECOVERY_REQUIRED"} for w in workers),
                "paused": sum(w["status"] == "PAUSED" for w in workers)}
