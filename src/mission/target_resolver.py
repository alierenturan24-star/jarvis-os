from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.github.categories import SUPPORTED_CATEGORIES
from src.mission.models import MissionType


class TargetKind(str, Enum):
    """Mission.target'ın taşıyabileceği 4 hedef türü (Sprint 31B tasarımı)."""

    REPOSITORY = "repository"
    OWNER = "owner"
    CATEGORY = "category"
    FREE_TEXT = "free_text"


@dataclass(frozen=True)
class Target:
    """Bir Mission'ın TEK, paylaşılan hedef tanımı.

    Mission oluşturulurken BİR KEZ ``TargetResolver`` ile üretilir; tüm
    departmanlar (browser/github/evaluation/sandbox/integration) AYNI
    ``Target`` nesnesini okur (``task.metadata["target"]`` üzerinden) --
    hiçbiri kendi başına tekrar kategori/URL çözümlemesi YAPMAZ.
    """

    kind: TargetKind

    # kind=REPOSITORY için dolu:
    owner: Optional[str] = None
    repo: Optional[str] = None
    full_name: Optional[str] = None
    url: Optional[str] = None

    # Her ``kind`` için (REPOSITORY/OWNER dahil) opsiyonel bağlam: mission
    # türünden türetilen "en yakın" GitHub arama kategorisi -- CATEGORY
    # türünde aramanın ta kendisi, REPOSITORY/OWNER türünde ise
    # değerlendirme/relevance bağlamı için yardımcı ipucu.
    category_hint: Optional[str] = None

    # kind=FREE_TEXT için dolu:
    text: Optional[str] = None
    # Strong project/repository name explicitly supplied by the user when
    # owner/repo is not yet known. Search results must match this name.
    requested_name: Optional[str] = None


# Sprint 21'de eklenmiş, Sprint 31A'da department_adapters.py'den
# TAŞINDI -- MissionType -> GitHub arama kategorisi eşlemesi
# DEĞİŞTİRİLMEDİ, yalnızca doğal yeri olan hedef-çözümleme katmanına
# taşındı (department_adapters.py <-> target_resolver.py arasında
# dairesel import oluşmaması için de gerekliydi).
MISSION_TYPE_TO_GITHUB_CATEGORY: dict[MissionType, str] = {
    MissionType.YOUTUBE: "youtube automation",
    MissionType.BROWSER: "browser agent",
    MissionType.FINANCE: "finance ai",
    MissionType.MEDIA: "video generation",
    MissionType.LEARNING: "llm",
    MissionType.AI_DISCOVERY: "llm",
    MissionType.CODE: "ai agent",
    MissionType.GITHUB: "ai agent",
    MissionType.SECURITY: "ai agent",
    MissionType.SOCIAL_MEDIA: "ai agent",
    MissionType.AUTOMATION: "ai agent",
    MissionType.RESEARCH: "ai agent",
}

# Mission repair (real Swiss-Insider-Shorts failure): a content/production
# mission type (make a video/post ABOUT a topic) is not, by itself, a
# request to find/install a GitHub tool. Mapping these types to a GitHub
# search category UNCONDITIONALLY (as the table above does) is what made
# every YOUTUBE mission's default Target a "youtube automation" GitHub
# category search -- even a pure domain/content-research goal with no
# tooling need at all -- which is how an unrelated repo ended up being
# opened as the mission's "target". For these types the GitHub-category
# fallback now requires an explicit ACQUISITION signal in the text (see
# ``has_acquisition_signal``); domain/content research on its own falls
# through to FREE_TEXT instead. Mission types that are fundamentally ABOUT
# finding/evaluating a tool or repo (AI_DISCOVERY, CODE, GITHUB, FINANCE's
# trading-bot search, ...) are UNCHANGED -- this table entry still applies
# unconditionally for those.
_CONTENT_MISSION_TYPES = frozenset({
    MissionType.YOUTUBE, MissionType.SOCIAL_MEDIA, MissionType.MEDIA,
})

# Generic capability/acquisition vocabulary: a content-mission goal must
# contain one of these before it's treated as ALSO needing a GitHub/tool
# search. Deliberately generic (no "Swiss"/"Bongetis"/topic-specific
# words) -- this is a vocabulary check, not a per-mission special case.
_ACQUISITION_SIGNAL_SUBSTRINGS = (
    "repo", "github", "gitlab", "açık kaynak", "acik kaynak",
    "kurulum", "install", "sağlayıcı", "saglayici", "provider",
    "capability", "yetenek", "araç", "arac", "tool", "model",
)
# Short/common fragments checked as whole words only, to avoid matching
# inside unrelated words (e.g. "kur" inside "kurtarma"/"kurgu").
_ACQUISITION_SIGNAL_WORDS = ("kur",)


def has_acquisition_signal(text: str) -> bool:
    """``True`` yalnızca metin GERÇEKTEN bir araç/repo/sağlayıcı EDİNME
    sinyali içeriyorsa (bkz. yukarıdaki sabitler) -- düz bir konu/içerik
    araştırması (ör. "en güçlü fırsatı araştır") ASLA eşleşmez."""

    lowered = (text or "").casefold()
    if any(cue in lowered for cue in _ACQUISITION_SIGNAL_SUBSTRINGS):
        return True
    return any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in _ACQUISITION_SIGNAL_WORDS)


def _category_hint_from_text_and_mission_type(
    text: str, mission_type: Optional[MissionType]
) -> Optional[str]:
    """Eski ``resolve_search_category``'nin ("ai agent" son-çare
    varsayılanı HARİÇ) aynı iki adımı: (1) metin, desteklenen
    kategorilerden birini kelimesi kelimesine içeriyor mu, (2) yoksa
    mission_type eşlemesi. Hiçbiri yoksa ``None`` döner -- bu, TargetResolver'ın
    gerektiğinde FREE_TEXT'e düşebilmesi için kasıtlıdır; "ai agent"
    varsayılanı burada UYGULANMAZ (bkz. ``resolve_search_category``)."""

    lowered = (text or "").lower()
    for category in SUPPORTED_CATEGORIES:
        if category in lowered:
            return category
    # A domain label is not a capability.  Preserve the requested operation:
    # finance goals that ask to build/test/compare trading behaviour need
    # executable trading/backtest tooling, not generic "finance AI" repos.
    finance_domain = mission_type == MissionType.FINANCE or any(cue in lowered for cue in (
        "finance", "finans", "piyasa", "market", "borsa", "portfolio", "portföy",
    ))
    if finance_domain and any(cue in lowered for cue in (
        "stratej", "strategy", "backtest", "paper", "işlem", "trade", "trading",
        "out-of-sample", "oos", "portföy", "portfolio", "risk",
    )):
        return "trading bot"
    if mission_type is not None:
        mapped = MISSION_TYPE_TO_GITHUB_CATEGORY.get(mission_type)
        if mapped is not None and mission_type in _CONTENT_MISSION_TYPES and not has_acquisition_signal(text):
            return None
        return mapped
    return None


def resolve_search_category(text: str, mission_type: Optional[MissionType] = None) -> str:
    """GERİYE DÖNÜK UYUMLULUK için korunan fonksiyon (önceki yeri:
    ``src.mission.department_adapters``, Sprint 21). Davranışı BİREBİR
    AYNI: metin eşleşmesi -> mission_type eşlemesi -> "ai agent".

    Departman adaptörleri (github/evaluation/sandbox/integration) artık
    bunu DOĞRUDAN çağırmıyor -- kategori çözümlemesi yalnızca
    ``TargetResolver`` bir ``CATEGORY`` türü üretirken, TEK bir yerden
    yapılıyor (bkz. ``TargetResolver.resolve``). Bu fonksiyon yalnızca
    doğrudan çağıran eski/harici kod ve mevcut testler için korunuyor.
    """

    return _category_hint_from_text_and_mission_type(text, mission_type) or "ai agent"


# --- URL / repo / owner çıkarımı ------------------------------------------------
#
# Sprint 28B'de department_orchestrator.py içinde (yalnızca "browser"
# departmanı için) yazılmış olan URL/repo-slug çıkarım mantığı, Sprint
# 31A'da BURAYA TAŞINDI -- artık yalnızca browser değil, TÜM departmanlar
# aynı çıkarımı (TargetResolver üzerinden) paylaşıyor.

_URL_PATTERN = re.compile(r"https?://\S+")
_GITHUB_REPO_URL_PATTERN = re.compile(
    r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"
)
_GITHUB_OWNER_URL_PATTERN = re.compile(
    r"https?://github\.com/([A-Za-z0-9_.-]+)/?(?=\s|$)"
)
_GITHUB_REPO_SLUG_PATTERN = re.compile(r"\b([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)\b")
_OWNER_ONLY_EXCLUDED = {"search", "topics", "orgs", "sponsors", "marketplace", "settings"}
_GITHUB_MENTION_PATTERN = re.compile(r"github", re.IGNORECASE)
# Sprint 38 canlı testinde yakalandı: "github" kelimesi metnin HERHANGİ bir
# yerinde geçtiğinde, TÜM metindeki ilk "kelime/kelime" deseni bir repo
# slug'ı sanılıyordu -- ör. "... GitHub repoları ... Hangi ücretsiz
# AI/provider'ları kullandığını ..." cümlesinde, "github" ile hiçbir ilgisi
# olmayan "AI/provider" ifadesi yanlışlıkla owner/repo sanıldı. Artık slug
# taraması yalnızca "github" kelimesinin bu kadar YAKININDA yapılır.
_SLUG_PROXIMITY_WINDOW = 80
_NAMED_PROJECT_PATTERNS = (
    re.compile(r"\b([A-Za-z0-9][A-Za-z0-9_.-]{1,80})\s+(?:adlı|isimli)\s+(?:açık\s+kaynak\s+)?(?:proje\w*|repo\w*)", re.IGNORECASE),
    re.compile(r"\b([A-Za-z0-9][A-Za-z0-9_.-]{1,80})\s+(?:repo(?:su|sunu)?|proje(?:si|sini)?)\b", re.IGNORECASE),
)
_GENERIC_TARGET_NAMES = {"github", "gitlab", "bu", "bir", "açık", "kaynak"}
# Mission repair (real Swiss-Insider-Shorts failure): the bare hyphenated-
# token fallback below is meant to catch a slug-shaped project name (e.g.
# "jarvis-os", "gpt-4"). It must NOT catch a numeric list/range artifact
# (e.g. "1-2", "10-20") -- those routinely appear in ranked-list/step text
# ("top 1-2 opportunities", "adım 3-4") and are never a project name. Real
# project slugs always contain at least one letter.
_NUMERIC_RANGE_PATTERN = re.compile(r"^\d+(?:-\d+)+$")


def _extract_requested_name(text: str) -> Optional[str]:
    for pattern in _NAMED_PROJECT_PATTERNS:
        match = pattern.search(text or "")
        if match and match.group(1).casefold() not in _GENERIC_TARGET_NAMES:
            return match.group(1)
    for hyphenated in re.finditer(r"\b([A-Za-z0-9]+-[A-Za-z0-9-]+)\b", text or ""):
        candidate = hyphenated.group(1)
        if not _NUMERIC_RANGE_PATTERN.match(candidate):
            return candidate
    object_match = re.match(
        r'^\s*["“]?([A-Z][A-Za-z0-9_.-]*(?:\s+[A-Z][A-Za-z0-9_.-]*){0,3})'
        r"(?:['’](?:yi|yı|yu|yü|i|ı|u|ü))?\s+"
        r"(?:araştır\w*|incele\w*|değerlendir\w*)\b",
        text or "",
    )
    if object_match and object_match.group(1).casefold() not in _GENERIC_TARGET_NAMES:
        return object_match.group(1)
    return None


def _normalized_repo_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def target_matches_repo(target: Target, repo) -> bool:
    if not target.requested_name:
        return True
    expected = _normalized_repo_name(target.requested_name)
    candidates = (
        getattr(repo, "name", ""),
        str(getattr(repo, "full_name", "")).rsplit("/", 1)[-1],
    )
    return any(_normalized_repo_name(candidate) == expected for candidate in candidates)


def _extract_repository(text: str) -> Optional[tuple[str, str]]:
    """Önce açık bir ``github.com/sahip/repo`` URL'i, yoksa "github"
    kelimesinin YAKININDA bir ``sahip/repo`` deseni arar.

    Bare-slug taraması, URL'LER ÇIKARILMIŞ metin üzerinde yapılır --
    aksi halde ``https://github.com/owner`` (repo'suz, tek segmentli bir
    URL) içindeki ``github.com/owner`` parçası yanlışlıkla bir
    ``owner/repo`` çifti sanılabiliyordu (canlı test sırasında
    yakalandı)."""

    match = _GITHUB_REPO_URL_PATTERN.search(text)
    if match:
        owner = match.group(1).strip("/.")
        repo = match.group(2).strip("/.,")
        if owner and repo:
            return owner, repo

    text_without_urls = _URL_PATTERN.sub(" ", text)

    for mention in _GITHUB_MENTION_PATTERN.finditer(text_without_urls):
        window_start = max(0, mention.start() - _SLUG_PROXIMITY_WINDOW)
        window_end = mention.end() + _SLUG_PROXIMITY_WINDOW
        window = text_without_urls[window_start:window_end]

        slug_match = _GITHUB_REPO_SLUG_PATTERN.search(window)
        if not slug_match:
            continue

        owner = slug_match.group(1).strip("/.")
        repo = slug_match.group(2).strip("/.,")
        # GitHub kullanıcı adları/organizasyonları NOKTA İÇEREMEZ -- bu,
        # "..com" gibi bir alan adı parçasının (ör. şemasız
        # "github.com/owner") yanlışlıkla owner sanılmasını engeller.
        if not owner or not repo or "." in owner:
            continue
        return owner, repo

    return None


def _extract_owner(text: str) -> Optional[str]:
    """Yalnızca ``github.com/sahip`` biçiminde (ikinci bir yol bileşeni
    OLMADAN) bir GitHub sahibi/organizasyonu belirtilmişse döner."""

    match = _GITHUB_OWNER_URL_PATTERN.search(text)
    if not match:
        return None

    owner = match.group(1).strip("/.")
    if not owner or owner.lower() in _OWNER_ONLY_EXCLUDED:
        return None
    return owner


class TargetResolver:
    """Ham mission metnini TEK bir ``Target``'a çözümler.

    Stateless (``DomEngine`` ile aynı tasarım deseni, Sprint 27): hiçbir
    durum tutmaz, her çağrı bağımsızdır. ``resolve()``, Mission
    oluşturulurken YALNIZCA BİR KEZ çağrılır (bkz. ``mission_engine.py``);
    üretilen ``Target``, tüm departmanlarca (``task.metadata["target"]``
    üzerinden) paylaşılır -- hiçbir departman kendi başına tekrar
    kategori/URL çözümlemesi YAPMAZ.

    Öncelik sırası:
      1. Açık bir GitHub repo URL'i veya (yalnızca "github" bağlamında)
         ``sahip/repo`` deseni -> REPOSITORY.
      2. Yalnızca bir GitHub sahibi/organizasyonu (repo yok) -> OWNER.
      3. Metin bilinen bir kategoriyi içeriyor VEYA mission_type bir
         kategoriye eşleniyor -> CATEGORY.
      4. Herhangi bir URL (github dışı) -> FREE_TEXT (url metniyle).
      5. Hiçbiri -> FREE_TEXT (ham metinle).
    """

    def resolve(self, text: str, mission_type: Optional[MissionType] = None) -> Target:
        text = text or ""
        category_hint = _category_hint_from_text_and_mission_type(text, mission_type)
        requested_name = _extract_requested_name(text)

        repository = _extract_repository(text)
        if repository is not None:
            owner, repo = repository
            return Target(
                kind=TargetKind.REPOSITORY,
                owner=owner,
                repo=repo,
                full_name=f"{owner}/{repo}",
                url=f"https://github.com/{owner}/{repo}",
                category_hint=category_hint,
            )

        owner = _extract_owner(text)
        if owner is not None:
            return Target(
                kind=TargetKind.OWNER,
                owner=owner,
                url=f"https://github.com/{owner}",
                category_hint=category_hint,
            )

        if category_hint is not None:
            return Target(
                kind=TargetKind.CATEGORY, category_hint=category_hint,
                requested_name=requested_name,
            )

        url_match = _URL_PATTERN.search(text)
        if url_match:
            return Target(
                kind=TargetKind.FREE_TEXT, text=url_match.group(0).rstrip(".,)"),
                requested_name=requested_name,
            )

        return Target(kind=TargetKind.FREE_TEXT, text=text, requested_name=requested_name)
