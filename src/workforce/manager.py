from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.control_center.store import ControlCenterStore, utc_now
from src.media.quality import validate_media_goal_artifact
from src.workforce.vault import WindowsCredentialVault


WORKER_DEFINITIONS = (
    ("deniz", "DENİZ", "YOUTUBE", "YouTube Channel Operator", "youtube-de", "Germany", "de-DE"),
    ("ceren", "CEREN", "YOUTUBE", "YouTube Channel Operator", "youtube-us", "United States", "en-US"),
    ("sinem", "SİNEM", "YOUTUBE", "YouTube Channel Operator", "youtube-ch", "Switzerland", "CHANNEL_CONFIG"),
    ("eren", "EREN", "FINANCE", "Strategy Research & Exploration", None, None, None),
    ("cemo", "CEMO", "FINANCE", "Independent Risk / OOS / Qualification Reviewer", None, None, None),
    ("eylem", "EYLEM", "QUALITY", "Content Quality & Independent Review", None, None, None),
    ("ali", "ALİ", "OPERATIONS", "Scheduling / Recovery / Operations", None, None, None),
)

STATUSES = {"IDLE", "SCHEDULED", "RESEARCHING", "PLANNING", "WORKING", "VALIDATING",
            "WAITING_APPROVAL", "WAITING_FOR_HUMAN", "ACCOUNT_REAUTH_REQUIRED", "BLOCKED",
            "RECOVERY_REQUIRED", "PAUSED"}
PROHIBITED_PERMISSIONS = {"password_change", "recovery_change", "two_factor_change",
                          "account_delete", "ownership_transfer", "security_settings_change",
                          "youtube_publish", "real_money_trade"}
_DEFAULT_CHANNEL_LIMITS = {"max_pending_productions_per_channel": 2,
                           "max_waiting_approvals_per_channel": 1,
                           "daily_production_budget": 1, "daily_publication_budget": 1}


def channel_goal_tag(channel_id: str) -> str:
    return f"[WORKFORCE_CHANNEL:{channel_id}]"


def ensure_channel_tag(goal: str, channel_id: str) -> str:
    """Prefix goal with the channel scope tag MediaAgent resolves, unless already present.

    Preserves a caller-supplied goal (e.g. a queued production request) instead of
    replacing it, while still guaranteeing MediaAgent can scope production to the
    right channel instead of falling back to MediaManager's Germany/de-DE defaults.
    """
    tag = channel_goal_tag(channel_id)
    return goal if tag in goal else f"{tag} {goal}"


def _youtube_memory() -> dict:
    return {"productions": [], "characters": {}, "series": {}, "story_state": {},
            "shorts_history": [], "long_video_history": [], "titles": [], "thumbnails": [],
            "publication_history": [], "experiments": [], "failures": [], "next_production_changes": [],
            "analytics": {"source": "NOT_CONNECTED", "records": []}}


class WorkforceManager:
    def __init__(self, store: ControlCenterStore, *, notifier: Callable[[str, str, str], None] | None = None) -> None:
        self.store, self.notifier = store, notifier
        self.vault = WindowsCredentialVault()
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        now = utc_now()
        def mutate(state):
            workforce = state.setdefault("workforce", {"workers": {}, "decisions": [],
                "schedule_executions": [], "cleanup_audits": [], "active_channel_id": None})
            workers = workforce.setdefault("workers", {})
            channels = state.setdefault("channels", {})
            for wid, name, division, role, channel_id, market, language in WORKER_DEFINITIONS:
                workers.setdefault(wid, {"worker_id": wid, "name": name, "division": division, "role": role,
                    "status": "IDLE", "enabled": True, "current_goal": "", "current_mission_id": "",
                    "current_task": "", "channel_id": channel_id, "finance_scope": "PAPER_RESEARCH" if division == "FINANCE" else None,
                    "schedule": self._default_schedule(division),
                    "last_started_at": None, "last_completed_at": None, "last_error": "", "decisions": [],
                    "learning_refs": [], "performance": {"runs": 0, "completed": 0, "failed": 0},
                    "permissions": {"autonomous": ["research", "planning", "validation", "learning", "safe_recovery"],
                                    "prohibited": sorted(PROHIBITED_PERMISSIONS)},
                    "capability_access": self._capabilities(division, role), "created_at": now, "updated_at": now,
                    "last_result": "", "progress": 0.0, "needs_approval": False})
                if channel_id:
                    channels.setdefault(channel_id, {"channel_id": channel_id, "market": market, "language": language,
                        "identity": {"operator_worker_id": wid, "status": "NOT_CONNECTED", "target_audience": "children 5-9"},
                        "startup_policy": {"mode": "SHORTS_FIRST", "adaptive_when_analytics_available": True},
                        "limits": dict(_DEFAULT_CHANNEL_LIMITS),
                        "youtube_learning": _youtube_memory(), "production_queue": [], "schedule": {},
                        "storage": {"retained": [], "deleted": []}, "created_at": now, "updated_at": now})
                    # setdefault above only fires for a brand-new channel; a channel record
                    # persisted before "limits" existed in this schema stays without it, so
                    # assert_youtube_capacity's channel["limits"] KeyErrors on every real
                    # dispatch for that channel. Backfill it onto pre-existing records too.
                    channels[channel_id].setdefault("limits", dict(_DEFAULT_CHANNEL_LIMITS))
            state.setdefault("account_assignments", [])
            state.setdefault("publications", [])
        self.store.update(mutate)

    @staticmethod
    def _default_schedule(division: str) -> dict:
        jobs = ([{"job_type": "RESEARCH", "days": [0, 1, 2, 3, 4], "time": "09:00"},
                 {"job_type": "PRODUCTION", "days": [1, 4], "time": "10:00"},
                 {"job_type": "PUBLICATION", "days": [1, 4], "time": "18:00"}]
                if division == "YOUTUBE" else
                [{"job_type": "PAPER_RESEARCH", "days": [0, 2, 4], "time": "10:00"}]
                if division == "FINANCE" else [])
        return {"enabled": False, "timezone": "Europe/Berlin", "jobs": jobs,
                "next_run_at": None, "last_execution_id": None}

    @staticmethod
    def _capabilities(division: str, role: str) -> list[str]:
        if division == "YOUTUBE": return ["content_opportunity", "youtube_learning", "story_generation", "scene_generation",
            "character_visual_generation", "motion_generation", "narration_generation", "thumbnail_generation", "video_render"]
        if role.startswith("Strategy"): return ["market_data", "strategy_exploration", "backtest", "oos", "performance_evidence"]
        if role.startswith("Independent Risk"): return ["finance_evidence_review", "paper_qualification"]
        if division == "QUALITY": return ["technical_validation", "semantic_validation", "continuity_review", "duplicate_review"]
        return ["persistent_scheduler", "restart_recovery", "duplicate_job_prevention", "retention_planning", "notifications"]

    def workers(self) -> list[dict[str, Any]]:
        return list(self.store.snapshot()["workforce"]["workers"].values())

    def worker(self, worker_id: str) -> dict[str, Any]:
        state = self.store.snapshot(); worker = state["workforce"]["workers"].get(worker_id)
        if worker is None: raise KeyError("Worker bulunamadı")
        result = copy.deepcopy(worker)
        result["decision_history"] = [d for d in state["workforce"]["decisions"] if d["worker_id"] == worker_id][-100:]
        if worker.get("channel_id"): result["channel"] = state["channels"][worker["channel_id"]]
        result["approvals"] = [a for a in state.get("approvals", []) if a.get("worker_id") == worker_id]
        return result

    def set_status(self, worker_id: str, status: str, **fields) -> dict:
        if status not in STATUSES: raise ValueError("Invalid worker status")
        def mutate(state):
            worker = state["workforce"]["workers"][worker_id]
            worker.update(status=status, updated_at=utc_now(), **fields)
        return self.store.update(mutate)["workforce"]["workers"][worker_id]

    def pause(self, worker_id: str) -> dict: return self.set_status(worker_id, "PAUSED", enabled=True)
    def resume(self, worker_id: str) -> dict: return self.set_status(worker_id, "IDLE", last_error="")
    def disable(self, worker_id: str) -> dict: return self.set_status(worker_id, "PAUSED", enabled=False)

    def stop_all(self) -> list[dict]:
        for worker in self.workers(): self.set_status(worker["worker_id"], "PAUSED")
        return self.workers()

    def change_schedule(self, worker_id: str, schedule: dict) -> dict:
        timezone_name = str(schedule.get("timezone", "Europe/Berlin"))
        if timezone_name != "Europe/Berlin":
            try: ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError as error: raise ValueError("Invalid schedule timezone") from error
        current = self.worker(worker_id).get("schedule", {})
        jobs = schedule.get("jobs", current.get("jobs", []))
        if not isinstance(jobs, list) or len(jobs) > 8: raise ValueError("Invalid schedule jobs")
        normalized, seen = [], set()
        allowed_types = {"RESEARCH", "PRODUCTION", "PUBLICATION", "PAPER_RESEARCH", "FINANCE_REVIEW", "OPERATIONS"}
        for job in jobs:
            kind, at = str(job.get("job_type", "")).upper(), str(job.get("time", ""))
            days = sorted(set(int(day) for day in job.get("days", [])))
            if kind not in allowed_types or len(at) != 5 or at[2] != ":" or not all(0 <= day <= 6 for day in days):
                raise ValueError("Malformed schedule")
            hour, minute = map(int, at.split(":"))
            if hour > 23 or minute > 59 or not days: raise ValueError("Malformed schedule")
            key = (kind, tuple(days), at)
            if key in seen: raise ValueError("Duplicate schedule rejected")
            seen.add(key); normalized.append({"job_type": kind, "days": days, "time": at})
        next_run = schedule.get("next_run_at")
        if bool(schedule.get("enabled")) and not next_run and normalized:
            next_run = self._next_occurrence(normalized, timezone_name)
        allowed = {"enabled": bool(schedule.get("enabled")), "timezone": timezone_name, "jobs": normalized,
                   "cron": str(schedule.get("cron", ""))[:100],
                   "next_run_at": next_run, "last_execution_id": None}
        def mutate(state):
            state["workforce"]["workers"][worker_id].update(
                schedule=allowed, status="SCHEDULED" if allowed["enabled"] else "IDLE", updated_at=utc_now())
        return self.store.update(mutate)["workforce"]["workers"][worker_id]

    @staticmethod
    def _next_occurrence(jobs: list[dict], timezone_name: str, now: datetime | None = None) -> str:
        try: zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError: zone = datetime.now().astimezone().tzinfo
        local_now = (now or datetime.now(timezone.utc)).astimezone(zone); candidates = []
        for offset in range(8):
            day = local_now.date() + timedelta(days=offset)
            for job in jobs:
                if day.weekday() not in job["days"]: continue
                hour, minute = map(int, job["time"].split(":"))
                candidate = datetime.combine(day, datetime.min.time(), tzinfo=zone).replace(hour=hour, minute=minute)
                if candidate > local_now: candidates.append(candidate)
        if not candidates: raise ValueError("Schedule has no next occurrence")
        return min(candidates).astimezone(timezone.utc).isoformat(timespec="seconds")

    def due_jobs(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(timezone.utc); due = []
        for worker in self.workers():
            schedule = worker.get("schedule", {}); raw = schedule.get("next_run_at")
            if not worker.get("enabled") or not schedule.get("enabled") or not raw: continue
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if when <= now:
                jobs = schedule.get("jobs", [])
                matching = [j for j in jobs if now.astimezone().weekday() in j["days"]] or jobs[:1]
                if matching: due.append({"worker_id": worker["worker_id"], "scheduled_for": raw,
                                         "job_type": matching[0]["job_type"]})
        return due

    def advance_schedule(self, worker_id: str) -> None:
        schedule = self.worker(worker_id)["schedule"]
        next_run = self._next_occurrence(schedule.get("jobs", []), schedule.get("timezone", "Europe/Berlin"),
                                         datetime.now(timezone.utc) + timedelta(seconds=1))
        self.store.update(lambda s: s["workforce"]["workers"][worker_id]["schedule"].update(next_run_at=next_run))

    def assert_youtube_capacity(self, worker_id: str) -> dict:
        worker = self.worker(worker_id); channel_id = worker.get("channel_id")
        if not channel_id: raise ValueError("YouTube channel scope missing")
        state, channel = self.store.snapshot(), self.store.snapshot()["channels"][channel_id]
        pending = [x for x in channel.get("production_queue", []) if x.get("status") not in {"PUBLISHED_VERIFIED", "REJECTED"}]
        approvals = [x for x in state.get("approvals", []) if x.get("binding", {}).get("channel_id") == channel_id
                     and x.get("status") == "PENDING"]
        limits = channel["limits"]
        today = utc_now()[:10]
        produced_today = sum(str(x.get("created_at", "")).startswith(today) for x in channel.get("production_queue", []))
        if (len(pending) >= limits["max_pending_productions_per_channel"]
                or len(approvals) >= limits["max_waiting_approvals_per_channel"]
                or produced_today >= limits["daily_production_budget"]):
            self.set_status(worker_id, "WAITING_FOR_HUMAN", current_task="BACKLOG_LIMIT", last_error="BACKLOG_LIMIT")
            raise RuntimeError("WAITING_FOR_HUMAN / BACKLOG_LIMIT")
        return {"pending": len(pending), "waiting_approvals": len(approvals), "produced_today": produced_today,
                "limits": copy.deepcopy(limits)}

    def release_backlog_if_clear(self, worker_id: str) -> dict | None:
        """Drop a worker out of a stale WAITING_FOR_HUMAN/BACKLOG_LIMIT or
        WAITING_APPROVAL once every human-decision item it was waiting on for its
        channel has actually been resolved. Daily rate budgets are deliberately not
        part of this check: assert_youtube_capacity() re-evaluates them fresh on the
        next real dispatch, so re-checking them here would just reproduce the same
        BACKLOG_LIMIT for a genuinely exhausted daily budget -- correctly, not stuck.
        """
        state = self.store.snapshot()
        worker = state["workforce"]["workers"].get(worker_id)
        if worker is None or worker.get("status") not in {"WAITING_FOR_HUMAN", "WAITING_APPROVAL"}:
            return None
        channel_id = worker.get("channel_id")
        if not channel_id:
            return None
        channel = state["channels"].get(channel_id, {})
        pending = [x for x in channel.get("production_queue", []) if x.get("status") not in {"PUBLISHED_VERIFIED", "REJECTED"}]
        approvals = [x for x in state.get("approvals", []) if x.get("binding", {}).get("channel_id") == channel_id
                     and x.get("status") == "PENDING"]
        if pending or approvals:
            return None
        return self.set_status(worker_id, "IDLE", current_task="", current_mission_id="",
                                last_error="", needs_approval=False)

    def operations_health(self) -> dict:
        state = self.store.snapshot()
        return {"missed_or_recovery": sum(w.get("status") == "RECOVERY_REQUIRED" for w in self.workers()),
                "approval_backlog": sum(a.get("status") == "PENDING" for a in state.get("approvals", [])),
                "publication_verification_backlog": sum(p.get("publication_status") == "REMOTE_VERIFYING" for p in state.get("publications", [])),
                "duplicate_prevention": True, "cleanup_is_post_transaction": True, "checked_at": utc_now()}

    def claim_execution(self, worker_id: str, scheduled_for: str | None = None) -> str:
        key = f"{worker_id}:{scheduled_for or utc_now()}"; execution_id = uuid.uuid5(uuid.NAMESPACE_URL, key).hex
        def mutate(state):
            rows = state["workforce"]["schedule_executions"]
            if any(row["execution_id"] == execution_id for row in rows): raise RuntimeError("Duplicate schedule execution rejected")
            rows.append({"execution_id": execution_id, "worker_id": worker_id, "scheduled_for": scheduled_for,
                         "status": "CLAIMED", "created_at": utc_now()})
            state["workforce"]["workers"][worker_id]["schedule"]["last_execution_id"] = execution_id
        self.store.update(mutate); return execution_id

    def evaluate_missed_schedules(self, now: datetime | None = None) -> list[str]:
        """Persist missed work as recovery-required; never claim it completed."""
        now = now or datetime.now(timezone.utc); missed = []
        def mutate(state):
            for worker in state["workforce"]["workers"].values():
                schedule = worker.get("schedule", {})
                raw = schedule.get("next_run_at")
                if not schedule.get("enabled") or not raw: continue
                try: due = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                except ValueError: continue
                if due < now and not schedule.get("last_execution_id"):
                    worker.update(status="RECOVERY_REQUIRED", last_error=f"Missed schedule: {raw}", updated_at=utc_now())
                    missed.append(worker["worker_id"])
        self.store.update(mutate)
        return missed

    def decision(self, worker_id: str, *, goal: str, decision: str, why: str, evidence: dict,
                 capabilities_used: list[str], risk: str, expected_result: str, actual_result: str = "",
                 learning: str = "") -> dict:
        item = {"decision_id": uuid.uuid4().hex, "worker_id": worker_id, "timestamp": utc_now(),
                "goal": goal, "decision": decision, "why": why, "evidence": evidence,
                "capabilities_used": capabilities_used, "risk": risk, "expected_result": expected_result,
                "actual_result": actual_result, "learning": learning,
                "summary": f"{decision}: {why}"[:500]}
        self.store.update(lambda state: (state["workforce"]["decisions"].append(item),
            state["workforce"]["workers"][worker_id]["decisions"].append(item["decision_id"])))
        return item

    def youtube_goal(self, worker_id: str) -> str:
        worker = self.worker(worker_id)
        if worker["division"] != "YOUTUBE": raise ValueError("Worker YouTube operator değil")
        channel = worker["channel"]; language = channel["language"]
        return (f"{channel_goal_tag(channel['channel_id'])} {worker['name']} için {channel['market']} pazarında, "
                f"{language} dilinde SHORTS-FIRST kanal politikasını ve geçmiş channel learning/story hafızasını kullan. "
                "Bounded content opportunity seç; trend verisi yoksa TREND DATA UNAVAILABLE de. Yeni YouTube videosu planla ve üret. "
                "Gerçek MP4, audio, motion ve thumbnail üret; doğrula; yayınlama, approval queue'ya bırak.")

    def quality_review(self, production: dict, channel: dict) -> dict:
        artifact = Path(production.get("artifact", {}).get("final_video_path", ""))
        check = validate_media_goal_artifact(artifact, production.get("original_goal", "")) if artifact.is_file() else None
        gates = check.gates if check else {}

        def gate_passed(name: str) -> bool:
            return bool(check) and bool(gates.get(name, {}).get("passed"))

        # Sprint: real-production quality-gate audit -- requirement 32-33: QUALITY
        # APPROVED must be evidence-based across named categories (technical render
        # validity, research grounding, narrative coherence, visual relevance, visual
        # continuity, repetition, audio completeness, AV timing, Shorts structure,
        # publication readiness), each sourced from src.media.quality's single gate
        # authority (no second quality system). A live incident (production
        # 77b5c0b1e9c344d2ac1cbca052e85b7c, Swiss Insider/sinem) reached "QUALITY
        # APPROVED" with content unrelated to the requested goal, no stored research
        # evidence, a repeated 3-pose motion loop, and narration covering under a
        # third of the final timeline -- none of the OLD boolean checks below could
        # see any of that; the new gates below can.
        evidence = {"technical_validation": bool(check and check.technical_passed),
            "semantic_validation": bool(check and check.semantic_passed),
            "story_continuity": bool(production.get("creative", {}).get("ending")),
            "character_consistency": production.get("quality", {}).get("character_consistency", 0) >= 70,
            "motion": bool(check and check.body_motion_detected), "audio": bool(check and check.max_audio_db is not None and check.max_audio_db > -60),
            "thumbnail": bool(production.get("artifact", {}).get("thumbnail_path")),
            "language_market_fit": production.get("target_country_language") not in (None, "", "unspecified"),
            "duplicate_reuse": not bool(production.get("failure", {}).get("rejection_reasons")),
            "artifact_integrity": artifact.is_file() and artifact.stat().st_size > 0,
            "research_grounding": gate_passed("research_grounding"),
            "narrative_coherence": gate_passed("narrative_coherence"),
            "visual_relevance": gate_passed("visual_relevance"),
            "visual_continuity": gate_passed("visual_continuity"),
            "repetition": gate_passed("repetition"),
            "audio_completeness": gate_passed("audio_completeness"),
            "av_timing": gate_passed("av_timing"),
            "shorts_structure": gate_passed("shorts_structure")}
        passed = all(evidence.values())
        return {"review_id": uuid.uuid4().hex, "reviewer_worker_id": "eylem", "passed": passed,
                "decision": "QUALITY APPROVED" if passed else "QUALITY REJECTED",
                "evidence": evidence, "gate_detail": gates,
                "required_changes": [k for k, v in evidence.items() if not v], "created_at": utc_now()}

    def finance_review(self, lab: dict) -> dict:
        candidates = lab.get("candidates", [])
        checks = {"data_provenance": lab.get("market_truth_source") is True,
            "sample_size": all(sum(x.get("sample_bars", 0) for x in c.get("asset_results", [])) >= 120 for c in candidates),
            "fees_slippage": lab.get("fees_rate") is not None and lab.get("slippage_rate") is not None,
            "train_oos": all("train_metrics" in c and "out_of_sample_metrics" in c for c in candidates),
            "risk_metrics": all(all(k in c for k in ("max_drawdown", "profit_factor", "expectancy", "sharpe")) for c in candidates),
            "multi_asset_regime": all(len(c.get("assets_tested", [])) >= 2 and c.get("regimes_tested") for c in candidates),
            "look_ahead_protection": bool(candidates) and all(c.get("asset_results") for c in candidates)}
        eligible = [c for c in candidates if c.get("qualified") is True]
        passed = all(checks.values()) and bool(eligible)
        return {"review_id": uuid.uuid4().hex, "reviewer_worker_id": "cemo", "decision": "QUALIFIED FOR PAPER" if passed else "REJECTED",
                "paper_eligible": passed, "real_money": False, "checks": checks,
                "rejection_reasons": [k for k, v in checks.items() if not v] or ([] if passed else ["no independently qualified candidate"]),
                "created_at": utc_now()}

    def retention_plan(self, channel_id: str) -> dict:
        state = self.store.snapshot(); publications = [p for p in state.get("publications", [])
            if p.get("channel_id") == channel_id and p.get("remote_verified") is True]
        publications.sort(key=lambda p: p.get("verified_at", ""), reverse=True)
        protected = {p.get("production_id") for p in publications[:2]}
        eligible = [p for p in publications[2:] if p.get("production_id") not in protected]
        return {"channel_id": channel_id, "verified_count": len(publications), "protected_production_ids": sorted(protected),
                "eligible": eligible, "dry_run": True, "shorts_counted": True}

    def cleanup(self, channel_id: str, *, execute: bool = False) -> dict:
        plan = self.retention_plan(channel_id); deleted = []
        if execute:
            root = Path("workspace").resolve()
            active = {w.get("current_mission_id") for w in self.workers() if w.get("status") in {"WORKING", "VALIDATING"}}
            for publication in plan["eligible"]:
                if publication.get("mission_id") in active or not publication.get("remote_verified"): continue
                for raw in publication.get("large_artifacts", []):
                    path = Path(raw).resolve()
                    if root not in path.parents or path.is_symlink() or any(part in {"src", ".git", "config"} for part in path.parts):
                        raise ValueError("Cleanup path rejected")
                    if path.is_file() and path.suffix.lower() in {".mp4", ".wav", ".mp3"}:
                        path.unlink(); deleted.append(str(path))
        audit = {**plan, "execute": execute, "deleted": deleted, "audit_id": uuid.uuid4().hex, "created_at": utc_now()}
        self.store.update(lambda s: s["workforce"]["cleanup_audits"].append(audit)); return audit
