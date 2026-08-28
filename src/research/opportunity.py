from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

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
    sufficient: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected_topic": self.selected_topic,
            "location_or_market": self.location_or_market,
            "why_current": self.why_current,
            "supporting_evidence": list(self.supporting_evidence),
            "freshness_status": self.freshness_status,
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
        {"url": str(item.get("url", "")), "title": str(item.get("title", ""))}
        for item in (sources or []) if str(item.get("url", "")).strip()
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

    freshness = "CURRENT" if wants_current else "UNVERIFIED"
    why_current = "güncellik sinyali doğrulandı, bayat/eski yıl referansı bulunamadı" if wants_current else "güncellik açıkça istenmedi"

    return SelectedOpportunity(
        selected_topic=excerpt, location_or_market=location_or_market, why_current=why_current,
        supporting_evidence=evidence, freshness_status=freshness, sufficient=True,
        reason="",
    )
