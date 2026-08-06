from __future__ import annotations

import math

from src.github.models import RepoData
from src.github.scoring import (
    COPYLEFT_LICENSES,
    PERMISSIVE_LICENSES,
    UNCLEAR_LICENSES,
    days_since,
)

# JARVIS saf Python bir kod tabanı (bkz. src/). Bu yüzden dil uyumluluğu
# Python'a göre ölçeklenir; diğer diller CLI/REST/SDK üzerinden dolaylı
# entegre edilebilir ama doğrudan import edilemez.
COMPATIBILITY_BY_LANGUAGE = {
    "python": 100.0,
    "jupyter notebook": 75.0,
    "shell": 60.0,
    "typescript": 55.0,
    "javascript": 55.0,
    "go": 50.0,
    "rust": 50.0,
    "vue": 45.0,
    "html": 45.0,
    "java": 40.0,
    "c#": 40.0,
    "c++": 35.0,
    "c": 35.0,
}

MODULARITY_KEYWORDS = (
    "sdk", "api", "framework", "cli", "plugin", "modular", "library",
    "toolkit", "package", "server", "client",
)
CROSS_LANGUAGE_KEYWORDS = ("api", "sdk", "cli", "rest", "server")


def architecture_score(repo: RepoData) -> float:
    """Repo mimarisinin JARVIS'e entegre edilebilirliği: dil, modülerlik
    sinyalleri (açıklamadaki sdk/api/framework/cli gibi ifadeler) ve
    açık issue yükü (yüksek oran = olası mimari/istikrar borcu)."""

    score = 0.0

    language = (repo.language or "").strip().lower()
    if language == "python":
        score += 40.0
    elif language in ("typescript", "javascript"):
        score += 25.0
    else:
        score += 10.0

    description = (repo.description or "").lower()
    if any(keyword in description for keyword in MODULARITY_KEYWORDS):
        score += 30.0
    else:
        score += 10.0

    issue_ratio = repo.open_issues / (repo.stars + 1)
    if issue_ratio < 0.01:
        score += 30.0
    elif issue_ratio < 0.05:
        score += 20.0
    elif issue_ratio < 0.15:
        score += 10.0

    return round(min(100.0, max(0.0, score)), 1)


def activity_score(repo: RepoData) -> float:
    """Son commit'e olan yakınlığa dayalı aktiflik puanı."""

    age = days_since(repo.last_update)

    if age is None:
        return 30.0
    if age <= 7:
        return 100.0
    if age <= 30:
        return 90.0
    if age <= 90:
        return 75.0
    if age <= 180:
        return 55.0
    if age <= 365:
        return 35.0
    if age <= 730:
        return 15.0
    return 5.0


def community_score(repo: RepoData) -> float:
    """Yıldız, fork ve katkıcı sayısına dayalı topluluk büyüklüğü/sağlığı."""

    stars_component = min(50.0, math.log10(max(repo.stars, 0) + 1) * 12.0)
    forks_component = min(25.0, math.log10(max(repo.forks, 0) + 1) * 10.0)

    if repo.contributors_count is None:
        contributors_component = 15.0
    else:
        contributors_component = min(25.0, repo.contributors_count * (25.0 / 20.0))

    return round(min(100.0, stars_component + forks_component + contributors_component), 1)


def license_score(repo: RepoData) -> float:
    """Lisansın hukuki netliği ve JARVIS'e entegrasyon için uygunluğu."""

    license_key = (repo.license or "").strip().lower()

    if license_key in PERMISSIVE_LICENSES:
        return 100.0
    if license_key in COPYLEFT_LICENSES:
        return 60.0
    if license_key in UNCLEAR_LICENSES:
        return 20.0
    return 75.0  # taninan ama izinli/copyleft kumelerinde olmayan gercek bir SPDX kimligi


def security_score(repo: RepoData) -> float:
    """Doğrudan güvenlik taraması YAPILMAZ (klonlama yok); bunun yerine
    yama hızını/hukuki denetlenebilirliği etkileyen dolaylı sinyallere
    (arşiv durumu, lisans netliği, güncellik, çözülmemiş issue yükü)
    dayalı bir tahmin üretir."""

    score = 70.0

    if repo.archived:
        score -= 35.0

    if license_score(repo) <= 20.0:
        score -= 20.0

    if activity_score(repo) >= 90.0:
        score += 10.0

    issue_ratio = repo.open_issues / (repo.stars + 1)
    if issue_ratio > 0.2:
        score -= 10.0

    return round(min(100.0, max(0.0, score)), 1)


def compatibility_score(repo: RepoData) -> float:
    """JARVIS'in Python kod tabanıyla doğrudan/dolaylı uyumluluk."""

    language = (repo.language or "").strip().lower()
    score = COMPATIBILITY_BY_LANGUAGE.get(language, 30.0)

    description = (repo.description or "").lower()
    if language != "python" and any(keyword in description for keyword in CROSS_LANGUAGE_KEYWORDS):
        score += 10.0

    return round(min(100.0, max(0.0, score)), 1)


def maintenance_score(repo: RepoData) -> float:
    """Sürdürülebilirlik: aktiflik + katkıcı sayısına dayalı "bus factor".
    Arşivlenmiş bir repo artık bakım almadığı için diğer sinyallerden
    bağımsız olarak düşük sabit bir puana sabitlenir."""

    if repo.archived:
        return 15.0

    if repo.contributors_count is None:
        bus_factor_component = 50.0
    elif repo.contributors_count <= 1:
        bus_factor_component = 20.0
    elif repo.contributors_count <= 3:
        bus_factor_component = 50.0
    elif repo.contributors_count <= 10:
        bus_factor_component = 80.0
    else:
        bus_factor_component = 100.0

    score = 0.5 * activity_score(repo) + 0.5 * bus_factor_component
    return round(min(100.0, max(0.0, score)), 1)
