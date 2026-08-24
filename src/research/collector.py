from __future__ import annotations

import ipaddress
import time
from typing import Any
from urllib.parse import urlparse

from src.tools.web_search_tool import WebSearchTool


# Sprint: research/production pipeline audit -- 4 fixed search channels
# (GENERAL_WEB/GITHUB/ARXIV/HACKER_NEWS) + 1 optional OFFICIAL_DOCS when
# requested (see ``ResearchCollector.collect``). Exported so callers can
# size an outer/inner timeout budget from the REAL worst-case step count
# instead of a second, independently-maintained magic number.
MAX_SEARCH_STEPS = 5

PRIMARY_SOURCE_TYPES = {"OFFICIAL_DOCS", "OFFICIAL_API", "GITHUB", "ARXIV", "LOCAL", "USER_CONFIRMED"}
KNOWN_IDENTITIES = {
    "github": ("GitHub", "GITHUB", ("github.com",)),
    "arxiv": ("Arxiv", "ARXIV", ("arxiv.org", "export.arxiv.org")),
    "hacker news": ("Hacker News", "COMMUNITY", ("news.ycombinator.com",)),
}
CLICK_REDIRECTS = {
    "bing.com": ("/aclick", "/ck/a", "/fd/ls/"),
    "www.bing.com": ("/aclick", "/ck/a", "/fd/ls/"),
    "google.com": ("/aclk", "/url", "/pagead/"),
    "www.google.com": ("/aclk", "/url", "/pagead/"),
    "googleadservices.com": ("/pagead/", "/aclk"),
    "www.googleadservices.com": ("/pagead/", "/aclk"),
}


def _host_matches(hostname: str, domain: str) -> bool:
    """Match an exact host or its real subdomain, never a string lookalike."""
    host = hostname.rstrip(".").casefold()
    base = domain.rstrip(".").casefold()
    return host == base or host.endswith("." + base)


def _unsafe_hostname(hostname: str) -> bool:
    host = hostname.rstrip(".").casefold()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return not address.is_global


def classify_source(
    url: str,
    *,
    claimed_identity: str = "",
    claimed_type: str = "",
    verification_state: str = "",
) -> dict[str, Any]:
    """Return URL-derived source identity and fail-closed quality metadata.

    Search labels are deliberately absent from this function: a query channel is
    provenance about discovery, not proof of the result's identity.
    """
    raw_url = str(url or "").strip()
    result: dict[str, Any] = {
        "canonical_url": raw_url,
        "source_identity": "",
        "source_type": "WEB",
        "verification_state": "UNVERIFIED",
        "source_quality_reason": "UNVERIFIED_UNTRUSTED_NOT_DURABLE",
        "durable_eligible": False,
        "rejected": False,
    }
    try:
        parsed = urlparse(raw_url)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        if parsed.scheme.casefold() not in {"http", "https"} or not hostname or parsed.username or parsed.password:
            raise ValueError
    except (TypeError, ValueError):
        result.update(rejected=True, source_quality_reason="REDIRECT_DESTINATION_UNRESOLVED")
        return result

    result["source_identity"] = hostname
    if _unsafe_hostname(hostname):
        result.update(rejected=True, source_quality_reason="REDIRECT_DESTINATION_UNRESOLVED")
        return result

    for redirect_host, paths in CLICK_REDIRECTS.items():
        if _host_matches(hostname, redirect_host) and any(parsed.path.casefold().startswith(path) for path in paths):
            reason = "AD_CLICK_URL_REJECTED" if "aclick" in parsed.path.casefold() or "aclk" in parsed.path.casefold() or "pagead" in parsed.path.casefold() else "REDIRECT_DESTINATION_UNRESOLVED"
            result.update(rejected=True, source_quality_reason=reason)
            return result

    derived_identity = hostname
    derived_type = "WEB"
    derived_reason = "UNVERIFIED_UNTRUSTED_NOT_DURABLE"
    derived_verification = "UNVERIFIED"
    durable = False
    for identity, source_type, domains in KNOWN_IDENTITIES.values():
        if any(_host_matches(hostname, domain) for domain in domains):
            derived_identity, derived_type = identity, source_type
            if source_type in PRIMARY_SOURCE_TYPES:
                derived_verification = "VERIFIED_SOURCE"
                durable = True
                derived_reason = "CANONICAL_GITHUB_REPOSITORY" if source_type == "GITHUB" else "PRIMARY_SOURCE_PREFERRED"
            break

    normalized_claim = str(claimed_identity or "").strip().casefold()
    known_claim = KNOWN_IDENTITIES.get(normalized_claim)
    if known_claim and not any(_host_matches(hostname, domain) for domain in known_claim[2]):
        result.update(source_identity=derived_identity, source_type=derived_type, rejected=True,
                      source_quality_reason="SOURCE_IDENTITY_DOMAIN_MISMATCH")
        return result

    requested_type = str(claimed_type or "").strip().upper()
    # OFFICIAL_* is accepted only from an explicit verified adapter assertion.
    if requested_type in {"OFFICIAL_DOCS", "OFFICIAL_API"}:
        if str(verification_state).strip().upper() not in {"VERIFIED", "VERIFIED_SOURCE", "VERIFIED_ADAPTER"}:
            result.update(source_identity=derived_identity, source_type=derived_type, rejected=True,
                          source_quality_reason="SOURCE_IDENTITY_DOMAIN_MISMATCH")
            return result
        derived_type = requested_type
        derived_verification = "VERIFIED_ADAPTER"
        durable = True
        derived_reason = "PRIMARY_SOURCE_PREFERRED"

    result.update(source_identity=derived_identity, source_type=derived_type,
                  verification_state=derived_verification, durable_eligible=durable,
                  source_quality_reason=derived_reason)
    return result


def source_matches_preferences(source_type: str, preferences: list[str]) -> bool:
    normalized = {str(item).strip().upper() for item in preferences if str(item).strip()}
    if not normalized:
        return True
    return str(source_type).upper() in normalized


class ResearchCollector:

    def __init__(self) -> None:
        self.web = WebSearchTool()

    def collect(
        self,
        topic: str,
        max_results_per_source: int = 3,
        deadline: float | None = None,
        source_preferences: list[str] | None = None,
    ) -> list[dict]:
        preferences = [str(item).strip().upper() for item in (source_preferences or []) if str(item).strip()]
        searches = [
            {"search_channel": "GENERAL_WEB", "query": topic},
            {"search_channel": "GITHUB", "query": f"site:github.com {topic}"},
            {"search_channel": "ARXIV", "query": f"site:arxiv.org {topic}"},
            {"search_channel": "HACKER_NEWS", "query": f"site:news.ycombinator.com {topic}"},
        ]
        if "OFFICIAL_DOCS" in preferences:
            searches.insert(0, {"search_channel": "OFFICIAL_DOCS", "query": f"{topic} official documentation"})
        preferred_channels = {"GITHUB" if item == "GITHUB" else item for item in preferences}
        searches.sort(key=lambda row: 0 if row["search_channel"] in preferred_channels else 1)

        collected: list[dict] = []
        known_urls: set[str] = set()
        for search in searches:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise TimeoutError("RESEARCH_CYCLE_MAX_RUNTIME_EXCEEDED")
            response = self.web.search(
                query=search["query"], max_results=max_results_per_source,
                timeout_seconds=remaining if remaining is not None else 15.0,
            )
            if not response.get("success"):
                continue
            for item in response.get("results", []):
                url = str(item.get("url", "")).strip()
                if not url or url in known_urls:
                    continue
                known_urls.add(url)
                quality = classify_source(
                    url,
                    claimed_identity=str(item.get("source_identity", "")),
                    claimed_type=str(item.get("source_type", "")),
                    verification_state=str(item.get("verification_state", "")),
                )
                preference_match = source_matches_preferences(str(quality["source_type"]), preferences)
                reason = quality["source_quality_reason"]
                if preferences and not preference_match and not quality["rejected"]:
                    reason = "SOURCE_PREFERENCE_NOT_SATISFIED"
                collected.append({
                    "search_channel": search["search_channel"],
                    "title": str(item.get("title", "")).strip(),
                    "url": url,
                    "summary": str(item.get("summary", "")).strip(),
                    **quality,
                    "source_quality_reason": reason,
                    "source_preference_match": preference_match,
                })

        # Enforce preferences when at least one requested source was found. Keep
        # rejected rows for audit, but exclude non-preferred usable evidence.
        if preferences and any(row["source_preference_match"] and not row["rejected"] for row in collected):
            collected = [row for row in collected if row["source_preference_match"] or row["rejected"]]
        return sorted(collected, key=lambda row: (not row["source_preference_match"], row["rejected"]))
