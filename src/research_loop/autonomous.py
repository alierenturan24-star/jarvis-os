from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import time
import inspect
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from src.config.settings import Settings
from src.control_center.store import ControlCenterStore, utc_now
from src.knowledge.knowledge_base import KnowledgeBase
from src.providers.provider_manager import ProviderManager
from src.research.collector import classify_source, source_matches_preferences

DECISIONS = {"ACCEPT_NEW", "UPDATE_EXISTING", "NO_CHANGE", "CONFLICT", "INSUFFICIENT_EVIDENCE", "REJECT"}
PRIMARY_TYPES = {"OFFICIAL_DOCS", "OFFICIAL_API", "GITHUB", "LOCAL", "USER_CONFIRMED"}
UNTRUSTED_EXTERNAL_CONTENT = "UNTRUSTED_EXTERNAL_CONTENT"
INJECTION_MARKERS = ("ignore previous instructions", "send your api key", "run this command", "disable security")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class AutonomousResearchService:
    """Persistent V1 coordinator over the existing collector, KB, provider and CC store."""

    def __init__(self, store: ControlCenterStore | None = None, knowledge: KnowledgeBase | None = None,
                 collector: Any | None = None, provider_manager: ProviderManager | None = None,
                 probes: dict[str, Callable[[str], bool]] | None = None,
                 monotonic: Callable[[], float] | None = None) -> None:
        self.store = store or ControlCenterStore()
        self.knowledge = knowledge or KnowledgeBase()
        self.collector = collector
        self.providers = provider_manager or ProviderManager()
        self.probes = probes or {}
        self.monotonic = monotonic or time.monotonic

    def topics(self) -> list[dict[str, Any]]:
        return self.store.snapshot()["autonomous_research"]["topics"]

    def create_topic(self, name: str, description: str = "", **options: Any) -> dict[str, Any]:
        name = " ".join(name.split())
        if not name:
            raise ValueError("Topic name is required")
        now = utc_now()
        interval = max(Settings.RESEARCH_MIN_INTERVAL_SECONDS, int(options.get("research_interval", 86400)))
        row = {"id": uuid.uuid4().hex, "name": name, "description": description[:2000],
               "enabled": bool(options.get("enabled", True)), "priority": int(options.get("priority", 50)),
               "created_at": now, "updated_at": now, "last_researched_at": None,
               "next_research_at": (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat(timespec="seconds"),
               "research_interval": interval, "source_preferences": list(options.get("source_preferences", [])),
               "tags": list(options.get("tags", [])), "consecutive_failures": 0, "running_cycle_id": None}
        self.store.update(lambda s: s["autonomous_research"]["topics"].append(row))
        return row

    def set_enabled(self, topic_id: str, enabled: bool) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> None:
            row = self._find(state["autonomous_research"]["topics"], topic_id)
            row.update(enabled=bool(enabled), updated_at=utc_now())
        state = self.store.update(mutate)
        return self._find(state["autonomous_research"]["topics"], topic_id)

    def due_topics(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        return [row for row in self.topics() if row.get("enabled") and not row.get("running_cycle_id")
                and (_parse(row.get("next_research_at")) or now) <= now
                and row.get("consecutive_failures", 0) < Settings.RESEARCH_MAX_CONSECUTIVE_FAILURES]

    def run_due(self, now: datetime | None = None) -> list[dict[str, Any]]:
        return [self.run_topic(row["id"], reason="SCHEDULED") for row in self.due_topics(now)]

    def run_topic(self, topic_id: str, *, reason: str = "MANUAL", raw_findings: list[dict[str, Any]] | None = None,
                  max_runtime: float | None = None) -> dict[str, Any]:
        cycle_id = uuid.uuid4().hex
        started = utc_now()
        deadline = self.monotonic() + (Settings.RESEARCH_CYCLE_MAX_SECONDS if max_runtime is None else max_runtime)
        def check_deadline() -> None:
            if self.monotonic() >= deadline:
                raise TimeoutError("RESEARCH_CYCLE_MAX_RUNTIME_EXCEEDED")
        def claim(state: dict[str, Any]) -> None:
            topic = self._find(state["autonomous_research"]["topics"], topic_id)
            if not topic.get("enabled"):
                raise RuntimeError("Disabled topic cannot run")
            if topic.get("running_cycle_id"):
                raise RuntimeError("Duplicate research cycle rejected")
            topic["running_cycle_id"] = cycle_id
            state["autonomous_research"]["cycles"].append({"research_cycle_id": cycle_id, "topic_id": topic_id,
                "reason": reason, "started_at": started, "finished_at": None, "status": "RUNNING",
                "sources_checked": 0, "evidence_count": 0, "new_findings": 0, "updated_findings": 0,
                "unchanged_findings": 0, "conflicts": 0, "rejected_findings": 0, "knowledge_writes": 0, "errors": []})
        state = self.store.update(claim)
        topic = self._find(state["autonomous_research"]["topics"], topic_id)
        try:
            check_deadline()
            findings = raw_findings if raw_findings is not None else self._collect(topic, deadline)
            # Blocking network adapters cannot be killed safely; their own request timeout remains
            # authoritative while this cooperative deadline rejects their late result.
            check_deadline()
            if not findings:
                raise RuntimeError("OFFLINE_OR_NO_EXTERNAL_EVIDENCE")
            findings = findings[:Settings.RESEARCH_MAX_FINDINGS_PER_CYCLE]
            counters = {"new_findings": 0, "updated_findings": 0, "unchanged_findings": 0,
                        "conflicts": 0, "rejected_findings": 0, "knowledge_writes": 0}
            sources: set[str] = set()
            quality_reasons: dict[str, int] = {}
            staged: list[dict[str, Any]] = []
            for item in findings:
                check_deadline()
                item = dict(item); item["topic_id"] = topic_id; item["cycle_id"] = cycle_id
                provenance = self._provenance(item, topic.get("source_preferences", []))
                item["provenance"] = provenance
                if not item.get("tool"):
                    item["tool"] = self._candidate_from_finding(item)
                decision, reason_text = self.learning_decision(item)
                item.update(id=uuid.uuid4().hex, decision=decision, decision_reason=reason_text, recorded_at=utc_now())
                reason_code = str(provenance.get("source_quality_reason", "UNKNOWN"))
                quality_reasons[reason_code] = quality_reasons.get(reason_code, 0) + 1
                if decision in {"ACCEPT_NEW", "UPDATE_EXISTING", "NO_CHANGE", "CONFLICT"} and provenance.get("source_url"):
                    sources.add(provenance["source_url"])
                if decision == "ACCEPT_NEW": counters["new_findings"] += 1
                elif decision == "UPDATE_EXISTING": counters["updated_findings"] += 1
                elif decision == "NO_CHANGE": counters["unchanged_findings"] += 1
                elif decision == "CONFLICT": counters["conflicts"] += 1
                else: counters["rejected_findings"] += 1
                staged.append(item)
            check_deadline()
            # No unverified partial writes occur before all bounded validation has completed.
            for item in staged:
                record = self.knowledge.persist_fact(item, item["decision"])
                if record: counters["knowledge_writes"] += 1
                self.store.update(lambda s, row=item: s["autonomous_research"]["findings"].append(row))
                if item.get("tool") and item["decision"] in {"ACCEPT_NEW", "UPDATE_EXISTING", "NO_CHANGE"}:
                    self._discover_tool(item)
            counters["source_quality_reasons"] = quality_reasons
            self._finish(topic_id, cycle_id, True, len(sources), len(sources), counters)
        except TimeoutError as error:
            self._finish(topic_id, cycle_id, False, 0, 0, {}, str(error), status="TIMEOUT")
        except Exception as error:
            self._finish(topic_id, cycle_id, False, 0, 0, {}, str(error))
        return self.latest_cycle(topic_id)

    def learning_decision(self, finding: dict[str, Any]) -> tuple[str, str]:
        p = finding.get("provenance", {})
        content = " ".join(str(finding.get(key, "")) for key in ("subject", "predicate", "value", "excerpt"))
        if any(marker in content.casefold() for marker in INJECTION_MARKERS):
            return "REJECT", "External prompt-injection content quarantined as data"
        if p.get("source_quality_rejected"):
            return "REJECT", str(p.get("source_quality_reason") or "Source quality policy rejected evidence")
        if p.get("source_quality_reason") == "SOURCE_PREFERENCE_NOT_SATISFIED":
            return "INSUFFICIENT_EVIDENCE", "SOURCE_PREFERENCE_NOT_SATISFIED"
        if not p.get("durable_eligible"):
            return "INSUFFICIENT_EVIDENCE", str(p.get("source_quality_reason") or "UNVERIFIED_UNTRUSTED_NOT_DURABLE")
        required = (finding.get("subject"), finding.get("predicate"), finding.get("value"), p.get("source_identity"), p.get("source_url"))
        if not all(required):
            return "INSUFFICIENT_EVIDENCE", "External fact requires source identity and URL"
        if float(finding.get("confidence", 0)) < .5:
            return "INSUFFICIENT_EVIDENCE", "Confidence below deterministic threshold"
        identity = self.knowledge.fact_identity(str(finding["subject"]), str(finding["predicate"]))
        active = [row for row in self.knowledge.facts(finding.get("topic_id")) if row.get("fact_identity") == identity and row.get("status") == "ACTIVE"]
        if not active:
            return "ACCEPT_NEW", "Evidence-backed fact is novel"
        normalized = self.knowledge.normalize(str(finding["value"]))
        if any(row.get("normalized_value") == normalized for row in active):
            return "NO_CHANGE", "Exact or normalized duplicate"
        newest = max(active, key=lambda row: row.get("provenance", {}).get("retrieved_at", ""))
        new_time = _parse(p.get("published_at") or p.get("retrieved_at"))
        oldp = newest.get("provenance", {})
        old_time = _parse(oldp.get("published_at") or oldp.get("retrieved_at"))
        new_primary = p.get("source_type") in PRIMARY_TYPES
        old_primary = oldp.get("source_type") in PRIMARY_TYPES
        if new_time and old_time and new_time > old_time and (new_primary or not old_primary):
            return "UPDATE_EXISTING", "Newer equally-or-more reliable evidence supersedes active fact"
        return "CONFLICT", "Different supported value; deterministic metadata cannot resolve it"

    def _provenance(self, item: dict[str, Any], source_preferences: list[str] | None = None) -> dict[str, Any]:
        url = str(item.get("source_url") or item.get("url") or "").strip()
        excerpt = str(item.get("excerpt") or item.get("summary") or item.get("value") or "")
        quality = classify_source(
            url, claimed_identity=str(item.get("source_identity") or ""),
            claimed_type=str(item.get("source_type") or ""),
            verification_state=str(item.get("verification_state") or ""),
        )
        preferences = list(source_preferences or [])
        preference_match = source_matches_preferences(str(quality["source_type"]), preferences)
        reason = str(quality["source_quality_reason"])
        if preferences and not preference_match and not quality["rejected"]:
            reason = "SOURCE_PREFERENCE_NOT_SATISFIED"
        return {"source_url": quality["canonical_url"], "original_url": url,
                "source_identity": quality["source_identity"], "source_type": quality["source_type"],
                "search_channel": str(item.get("search_channel") or ""),
                "retrieved_at": str(item.get("retrieved_at") or utc_now()), "published_at": item.get("published_at"),
                "evidence_identity": hashlib.sha256(excerpt.encode("utf-8")).hexdigest() if excerpt else None,
                "verification_state": quality["verification_state"], "trust_boundary": UNTRUSTED_EXTERNAL_CONTENT,
                "source_quality_reason": reason, "source_quality_rejected": bool(quality["rejected"]),
                "source_preference_match": preference_match, "durable_eligible": bool(quality["durable_eligible"] and preference_match)}

    def _collect(self, topic: dict[str, Any], deadline: float) -> list[dict[str, Any]]:
        if self.collector is None:
            from src.research.collector import ResearchCollector
            self.collector = ResearchCollector()
        kwargs = {"max_results_per_source": max(1, Settings.RESEARCH_MAX_SOURCES_PER_CYCLE // 4)}
        if "deadline" in inspect.signature(self.collector.collect).parameters:
            kwargs["deadline"] = deadline
        if "source_preferences" in inspect.signature(self.collector.collect).parameters:
            kwargs["source_preferences"] = list(topic.get("source_preferences", []))
        rows = self.collector.collect(topic["name"], **kwargs)
        return [{"subject": row.get("title") or topic["name"], "predicate": "research_summary", "value": row.get("summary", ""),
                 "excerpt": row.get("summary", ""), "source_url": row.get("canonical_url") or row.get("url"),
                 "source_identity": row.get("source_identity"), "source_type": row.get("source_type", "WEB"),
                 "search_channel": row.get("search_channel"), "verification_state": row.get("verification_state", "UNVERIFIED"),
                 "confidence": .65} for row in rows]

    @staticmethod
    def _candidate_from_finding(finding: dict[str, Any]) -> dict[str, Any] | None:
        """Extract only a passive candidate from canonical GitHub repository evidence."""
        provenance = finding.get("provenance", {})
        if (provenance.get("source_type") != "GITHUB" or not provenance.get("durable_eligible")
                or provenance.get("source_quality_rejected")):
            return None
        parsed = urlparse(str(provenance.get("source_url", "")))
        if (parsed.hostname or "").rstrip(".").casefold() != "github.com":
            return None
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2 or parts[0].casefold() in {"features", "topics", "collections", "marketplace", "orgs", "settings"}:
            return None
        owner, repository = parts
        if repository.casefold().endswith(".git"):
            repository = repository[:-4]
        if not owner or not repository:
            return None
        return {"name": repository, "capability_id": f"github-{owner.casefold()}-{repository.casefold()}",
                "repository": f"{owner}/{repository}", "category": "RESEARCH_DISCOVERED_TOOL",
                "access_method": "MANUAL_ONLY", "discovery_state": "VERIFIED_CANDIDATE",
                "description": f"Research-discovered GitHub repository {owner}/{repository}"}

    def _discover_tool(self, finding: dict[str, Any]) -> None:
        spec = dict(finding["tool"]); name = str(spec.get("name", "")).strip()
        if not name: return
        official = finding["provenance"].get("source_type") in {"OFFICIAL_DOCS", "OFFICIAL_API", "GITHUB"}
        status = "VERIFIED_CANDIDATE" if official else "DISCOVERED"
        access = str(spec.get("access_method", "MANUAL_ONLY"))
        available = self._probe(access, spec)
        approval = bool(spec.get("requires_account") or spec.get("requires_api_key") and not spec.get("configured")
                        or spec.get("requires_oauth") or spec.get("requires_installation") and not available
                        or spec.get("requires_payment") or spec.get("publication") or spec.get("production_config_change")
                        or spec.get("unsafe_side_effect") or spec.get("finance_live")
                        or str(spec.get("side_effect_class", "READ_ONLY")) not in {"READ_ONLY", "REVERSIBLE"})
        if approval: status = "APPROVAL_REQUIRED"
        elif official and available: status = "VERIFIED_CANDIDATE"
        row = {**spec, "capability_id": spec.get("capability_id") or self.knowledge.normalize(name).replace(" ", "-"),
               "name": name, "status": status, "available": available, "requires_approval": approval,
               "last_verified_at": utc_now() if official else None, "source_evidence": finding["provenance"],
               "success_count": 0, "failure_count": 0, "last_used_at": None}
        def mutate(state: dict[str, Any]) -> None:
            research = state["autonomous_research"]
            existing = next((x for x in research["tools"] if x["capability_id"] == row["capability_id"]), None)
            if existing: existing.update(row)
            else: research["tools"].append(row)
            # Research discovery never grants runtime capability availability.
            # A separate approved executor must create ACTIVE_CAPABILITY state.
            if approval and not any(x.get("capability_id") == row["capability_id"] and x.get("status") == "PENDING" for x in research["proposals"]):
                requested_action = self._requested_action(spec)
                proposal_id, approval_id = uuid.uuid4().hex, uuid.uuid4().hex
                proposal = {"proposal_id": proposal_id, "id": proposal_id, "capability_id": row["capability_id"],
                    "tool": name, "requested_action": requested_action, "reason": spec.get("description", "Capability configuration required"),
                    "purpose": spec.get("description", ""), "source": finding["provenance"].get("source_url"),
                    "cost": spec.get("pricing_type", "UNKNOWN"), "risk": spec.get("risk", "HIGH"),
                    "approval_id": approval_id, "status": "PENDING", "created_at": utc_now(),
                    "recommendation": "Review only; approval does not execute the side effect"}
                research["proposals"].append(proposal)
                state["approvals"].append({"id": approval_id, "type": "capability_proposal", "status": "PENDING",
                    "what": f"{requested_action}: {name}", "why": proposal["reason"], "risk": proposal["risk"],
                    "cost": proposal["cost"], "expected_result": "APPROVED_PENDING_EXECUTOR",
                    "details": {"requested_action": requested_action, "capability_id": row["capability_id"],
                                "proposal_id": proposal_id, "no_automatic_execution": True},
                    "binding": {"proposal_id": proposal_id, "capability_id": row["capability_id"],
                                "requested_action": requested_action}, "created_at": utc_now()})
        self.store.update(mutate)

    @staticmethod
    def _requested_action(spec: dict[str, Any]) -> str:
        if spec.get("requires_installation"): return "INSTALL"
        if spec.get("requires_account"): return "ACCOUNT_CREATION"
        if spec.get("requires_api_key") and not spec.get("configured"): return "API_KEY_CONFIGURATION"
        if spec.get("requires_oauth"): return "OAUTH"
        if spec.get("requires_payment"): return "PAYMENT"
        if spec.get("publication"): return "PUBLICATION"
        if spec.get("production_config_change"): return "PRODUCTION_CONFIG_CHANGE"
        if spec.get("finance_live"): return "FINANCE_LIVE"
        return "UNSAFE_SIDE_EFFECT"

    def _probe(self, access: str, spec: dict[str, Any]) -> bool:
        name = str(spec.get("probe_name") or spec.get("name", ""))
        if access in self.probes: return bool(self.probes[access](name))
        if access == "CLI": return shutil.which(name) is not None
        if access == "PYTHON_PACKAGE": return importlib.util.find_spec(name) is not None
        if access == "PROVIDER":
            provider = self.providers.get(name); return bool(provider and provider.is_available())
        if access in {"API", "OAUTH_SERVICE"}: return bool(spec.get("configured", False))
        if access == "LOCAL_BINARY": return os.path.isfile(name) and os.access(name, os.X_OK)
        return False

    def _finish(self, topic_id: str, cycle_id: str, success: bool, sources: int, evidence: int,
                counters: dict[str, int], error: str | None = None, status: str | None = None) -> None:
        def mutate(state: dict[str, Any]) -> None:
            research = state["autonomous_research"]; topic = self._find(research["topics"], topic_id)
            cycle = self._find(research["cycles"], cycle_id, "research_cycle_id")
            failures = 0 if success else int(topic.get("consecutive_failures", 0)) + 1
            delay = topic["research_interval"] if success else min(topic["research_interval"] * (2 ** failures), 604800)
            topic.update(running_cycle_id=None, last_researched_at=utc_now(), consecutive_failures=failures,
                         next_research_at=(datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec="seconds"), updated_at=utc_now())
            cycle.update(status=status or ("COMPLETED" if success else "FAILED"), finished_at=utc_now(), sources_checked=sources,
                         evidence_count=evidence, errors=[] if success else [str(error)], **counters)
        self.store.update(mutate)

    def latest_cycle(self, topic_id: str) -> dict[str, Any]:
        rows = [x for x in self.store.snapshot()["autonomous_research"]["cycles"] if x["topic_id"] == topic_id]
        return rows[-1] if rows else {}

    def findings(self, topic_id: str | None = None) -> list[dict[str, Any]]:
        rows = self.store.snapshot()["autonomous_research"]["findings"]
        return [x for x in rows if topic_id is None or x["topic_id"] == topic_id]

    @staticmethod
    def _find(rows: list[dict[str, Any]], value: str, key: str = "id") -> dict[str, Any]:
        row = next((item for item in rows if item.get(key) == value), None)
        if row is None: raise KeyError(f"Unknown {key}: {value}")
        return row
