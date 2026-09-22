from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

from src.research.manager import staleness_warning, topic_wants_current_information
from src.utils.llm_utils import is_llm_failure

# Round 5 repair (real live-mission evidence): research correctly ran a
# current-events content-opportunity search for a media mission, but could
# not establish a Switzerland-specific current story -- it then drifted
# into an unrelated recommendation ("GitHub Foundations Certification"),
# and the downstream media task independently re-derived its own topic
# (a DIFFERENT string than research's own query) and silently fell back to
# generic evergreen content instead of noticing/reporting the gap. Two
# separate defects, both repaired here:
#
#   1. A long natural-language research report has no machine-checkable
#      signal for "is this actually about the requested market/location,
#      and is it actually current". ``SelectedOpportunity`` is a compact,
#      structured handoff -- reusing the SAME existing
#      ``task.metadata["report"]`` convention github/evaluation/sandbox/
#      integration already use for structured results (see
#      report_builder.py) -- instead of a second, parallel research
#      architecture.
#   2. "Is this evidence actually about the requested market" is answered
#      with the SAME deterministic word-overlap technique
#      ``src.media.quality._check_narrative_relevance`` already uses to
#      catch tautological goal-relevance (no new measurement invented).
#   3. Freshness reuses the EXISTING ``staleness_warning``/
#      ``topic_wants_current_information`` helpers (src/research/manager.py)
#      -- no second currency check.

_MIN_MARKET_OVERLAP_RATIO = 0.15  # matches quality.py's _NARRATIVE_RELEVANCE_MIN_OVERLAP
_DEFAULT_CURRENT_WINDOW_DAYS = 14
_MIN_CURRENT_SOURCES = 2
_WINDOW_PATTERNS = (
    re.compile(r"\bson\s+(\d+)\s+gün\w*", re.IGNORECASE),
    re.compile(r"\b(?:last|past)\s+(\d+)\s+days?", re.IGNORECASE),
)
_SWISS_MARKET_NAMES = ("isviçre", "isvicre", "switzerland", "schweiz", "suisse", "svizzera")
_TRUSTED_SWISS_DOMAINS = (
    "admin.ch", "parlament.ch", "snb.ch", "finma.ch", "srf.ch", "rts.ch", "rsi.ch",
    "swissinfo.ch", "nzz.ch", "tagesanzeiger.ch", "letemps.ch", "cdt.ch", "20min.ch",
    "watson.ch", "blick.ch", "bluewin.ch",
)

# Generic Turkish connector/function words -- excluded so a market context
# built from a short phrase (e.g. "İsviçre için", from
# ``department_orchestrator._media_research_context``) doesn't register
# false coverage merely because the summary ALSO happens to contain a
# common connector word like "için" ("for") -- a real bug caught while
# writing this module's own regression tests, not hypothetical.
_GENERIC_CONNECTOR_WORDS = {
    "için", "ile", "gibi", "kadar", "olan", "veya", "üzere", "değil",
    "diye", "dair", "karşı", "göre",
}


def _content_words(text: str) -> set[str]:
    return {
        w for w in re.findall(r"\w+", (text or "").casefold())
        if len(w) >= 4 and w not in _GENERIC_CONNECTOR_WORDS
    }


def _covers_market_context(location_or_market: str, summary: str) -> bool:
    market_words = _content_words(location_or_market)
    if not market_words:
        # No location/market context was actually requested -- nothing to
        # verify coverage against.
        return True
    return (len(market_words & _content_words(summary)) / len(market_words)) >= _MIN_MARKET_OVERLAP_RATIO


def _freshness_window_days(topic: str) -> int:
    for pattern in _WINDOW_PATTERNS:
        match = pattern.search(topic or "")
        if match:
            return max(1, min(int(match.group(1)), 31))
    return _DEFAULT_CURRENT_WINDOW_DAYS


def _parse_published_at(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _required_source_languages(topic: str) -> set[str]:
    lowered = "".join(
        char for char in unicodedata.normalize("NFKD", (topic or "").casefold())
        if not unicodedata.combining(char)
    )
    aliases = {
        "de": ("almanca", "german", "deutsch"),
        "fr": ("fransızca", "fransizca", "french", "français", "francais"),
        "it": ("italyanca", "italian", "italiano"),
    }
    return {code for code, names in aliases.items() if any(name in lowered for name in names)}


def _trusted_for_requested_market(host: str, location_or_market: str) -> bool:
    lowered = "".join(
        char for char in unicodedata.normalize("NFKD", (location_or_market or "").casefold())
        if not unicodedata.combining(char)
    )
    if not any(name in lowered for name in _SWISS_MARKET_NAMES):
        return True
    return any(host == domain or host.endswith("." + domain) for domain in _TRUSTED_SWISS_DOMAINS)


def _current_evidence(
    sources: list[dict] | tuple[dict, ...], *, topic: str, location_or_market: str,
    now: datetime | None = None,
) -> tuple[tuple[dict, ...], int]:
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window_days = _freshness_window_days(topic)
    evidence: list[dict] = []
    seen_hosts: set[str] = set()
    for item in sources or ():
        if item.get("rejected") is True:
            continue
        url = str(item.get("canonical_url") or item.get("url") or "").strip()
        published_at = _parse_published_at(
            item.get("published_at") or item.get("date") or item.get("published")
        )
        if not url or published_at is None:
            continue
        age_seconds = (reference - published_at).total_seconds()
        if age_seconds < -86400 or age_seconds > window_days * 86400:
            continue
        host = (urlparse(url).hostname or "").casefold().rstrip(".")
        if not host or host in seen_hosts or not _trusted_for_requested_market(host, location_or_market):
            continue
        seen_hosts.add(host)
        evidence.append({
            "url": url,
            "title": str(item.get("title", "")).strip(),
            "published_at": published_at.isoformat(),
            "source_identity": str(item.get("source_identity") or host).strip(),
            "publisher": str(item.get("publisher") or "").strip(),
            "source_language": str(item.get("source_language") or "").strip().casefold(),
        })
    return tuple(evidence), window_days


@dataclass(frozen=True)
class SelectedOpportunity:
    """Compact, structured research -> media handoff for a market/location
    content-discovery research call. Deliberately small: the full
    natural-language report remains available separately (research's own
    text return value, and the KnowledgeBase record) -- this is only the
    subset a downstream consumer (media planning) needs to decide whether
    it may proceed, and to ground its script/hook/scenes truthfully."""

    selected_topic: str
    location_or_market: str
    why_current: str
    supporting_evidence: tuple[dict, ...] = field(default_factory=tuple)
    freshness_status: str = "UNVERIFIED"  # CURRENT | STALE | UNVERIFIED | INSUFFICIENT_EVIDENCE
    freshness_window_days: int = 0
    sufficient: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected_topic": self.selected_topic,
            "location_or_market": self.location_or_market,
            "why_current": self.why_current,
            "supporting_evidence": list(self.supporting_evidence),
            "freshness_status": self.freshness_status,
            "freshness_window_days": self.freshness_window_days,
            "sufficient": self.sufficient,
            "reason": self.reason,
        }


def build_selected_opportunity(
    *,
    topic: str,
    location_or_market: str,
    summary: str,
    sources: list[dict] | tuple[dict, ...] = (),
    created_at: str = "",
) -> SelectedOpportunity:
    """Deterministic (no LLM call) truthfulness gate over an ALREADY-run
    research result. Never invents/upgrades relevance -- when the evidence
    doesn't actually establish a current, market-relevant story, returns
    ``sufficient=False`` with a truthful ``reason`` instead of promoting
    unrelated content into a "selected opportunity"."""

    evidence = tuple(
        {
            "url": str(item.get("canonical_url") or item.get("url") or ""),
            "title": str(item.get("title", "")),
            "published_at": str(item.get("published_at") or item.get("date") or ""),
            "source_identity": str(item.get("source_identity") or ""),
            "publisher": str(item.get("publisher") or ""),
        }
        for item in (sources or [])
        if str(item.get("canonical_url") or item.get("url") or "").strip() and item.get("rejected") is not True
    )

    summary = summary or ""
    if is_llm_failure(summary) or not summary.strip():
        return SelectedOpportunity(
            selected_topic="", location_or_market=location_or_market, why_current="",
            supporting_evidence=evidence, freshness_status="INSUFFICIENT_EVIDENCE",
            sufficient=False, reason="araştırma sonucu üretilemedi veya boş",
        )

    excerpt = summary.strip()[:240]

    if not _covers_market_context(location_or_market, summary):
        return SelectedOpportunity(
            selected_topic=excerpt, location_or_market=location_or_market, why_current="",
            supporting_evidence=evidence, freshness_status="INSUFFICIENT_EVIDENCE", sufficient=False,
            reason=(
                f"araştırma sonucu '{location_or_market}' konum/pazarına dair somut kanıt içermiyor "
                "(alakasız bir konuya kaymış olabilir)"
            ),
        )

    wants_current = topic_wants_current_information(topic)
    stale = staleness_warning(topic, summary)

    if wants_current and stale:
        return SelectedOpportunity(
            selected_topic=excerpt, location_or_market=location_or_market, why_current=stale,
            supporting_evidence=evidence, freshness_status="STALE", sufficient=False, reason=stale,
        )

    if not evidence:
        return SelectedOpportunity(
            selected_topic=excerpt, location_or_market=location_or_market,
            why_current="güncellik doğrulanamadı" if wants_current else "",
            supporting_evidence=evidence, freshness_status="INSUFFICIENT_EVIDENCE", sufficient=False,
            reason="hiçbir kaynak/referans toplanamadı",
        )

    if wants_current:
        dated_evidence, window_days = _current_evidence(
            sources, topic=topic, location_or_market=location_or_market,
        )
        required_languages = _required_source_languages(topic)
        found_languages = {str(item.get("source_language") or "") for item in dated_evidence}
        missing_languages = sorted(required_languages - found_languages)
        minimum_sources = max(_MIN_CURRENT_SOURCES, len(required_languages))
        if len(dated_evidence) < minimum_sources or missing_languages:
            language_reason = (
                f" Eksik kaynak dili: {', '.join(missing_languages)}."
                if missing_languages else ""
            )
            return SelectedOpportunity(
                selected_topic=excerpt, location_or_market=location_or_market,
                why_current="güncellik tarihli kaynaklarla doğrulanamadı",
                supporting_evidence=dated_evidence,
                freshness_status="INSUFFICIENT_EVIDENCE", sufficient=False,
                reason=(
                    f"son {window_days} gün içinde yayınlanmış en az {minimum_sources} bağımsız, "
                    "tarihli ve istenen pazara ait güvenilir kaynak doğrulanamadı; "
                    f"ücretli medya üretimi başlatılmadı.{language_reason}"
                ),
            )
        evidence = dated_evidence

    freshness = "CURRENT" if wants_current else "UNVERIFIED"
    why_current = (
        f"{len(evidence)} bağımsız kaynağın yayın tarihi istenen güncellik aralığında doğrulandı"
        if wants_current else "güncellik açıkça istenmedi"
    )

    return SelectedOpportunity(
        selected_topic=excerpt, location_or_market=location_or_market, why_current=why_current,
        supporting_evidence=evidence, freshness_status=freshness,
        freshness_window_days=window_days if wants_current else 0, sufficient=True,
        reason="",
    )


def selected_opportunity_has_verified_current_evidence(
    report: Any, *, now: datetime | None = None,
) -> bool:
    """Completion-time guard for a serialized SelectedOpportunity."""
    if not isinstance(report, dict) or report.get("sufficient") is not True:
        return False
    if report.get("freshness_status") != "CURRENT":
        return False
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window_days = max(1, min(int(report.get("freshness_window_days") or _DEFAULT_CURRENT_WINDOW_DAYS), 31))
    hosts: set[str] = set()
    for item in report.get("supporting_evidence") or ():
        if not isinstance(item, dict):
            continue
        published_at = _parse_published_at(item.get("published_at"))
        host = (urlparse(str(item.get("url") or "")).hostname or "").casefold().rstrip(".")
        if published_at is None or not host:
            continue
        age_seconds = (reference - published_at).total_seconds()
        if -86400 <= age_seconds <= window_days * 86400:
            hosts.add(host)
    return len(hosts) >= _MIN_CURRENT_SOURCES
