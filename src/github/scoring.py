from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from src.github.models import RepoData

PERMISSIVE_LICENSES = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "mpl-2.0", "isc"}
COPYLEFT_LICENSES = {"gpl-2.0", "gpl-3.0", "agpl-3.0", "lgpl-2.1", "lgpl-3.0"}
UNCLEAR_LICENSES = {"noassertion", "other", ""}
EXPERIMENTAL_KEYWORDS = (
    "experimental", "proof of concept", " poc ", "wip", "work in progress",
    "toy", "demo", "prototype", "deneysel",
)


def days_since(iso_timestamp: str) -> Optional[float]:
    """``iso_timestamp`` (ör. GitHub'ın ``pushed_at`` alanı) ile şu an
    arasındaki gün farkını döndürür; ayrıştırılamazsa/boşsa ``None``."""

    if not iso_timestamp:
        return None
    try:
        updated = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - updated).total_seconds() / 86400


def quality_score(repo: RepoData) -> float:
    """Kalite puanı (0-100): yıldız sayısı, aktif geliştirme/son commit,
    lisans uygunluğu ve açıklama kalitesine dayalı ağırlıklı toplam."""

    score = 0.0

    # Yıldız sayısı (log ölçek, max 35 puan) — 10 yıldız ile 100000 yıldız
    # arasındaki farkı doğrusal değil, azalan getiriyle ölçekler.
    score += min(35.0, math.log10(max(repo.stars, 0) + 1) * 11.5)

    # Aktif geliştirme / son commit (max 30 puan)
    age = days_since(repo.last_update)
    if age is not None:
        if age <= 30:
            score += 30.0
        elif age <= 90:
            score += 22.0
        elif age <= 180:
            score += 14.0
        elif age <= 365:
            score += 6.0

    # Lisans uygunluğu (max 20 puan)
    license_key = (repo.license or "").strip().lower()
    if license_key in PERMISSIVE_LICENSES:
        score += 20.0
    elif license_key in COPYLEFT_LICENSES:
        score += 12.0
    elif license_key and license_key not in UNCLEAR_LICENSES:
        score += 8.0

    # Açıklama kalitesi (max 15 puan)
    description = (repo.description or "").strip()
    if len(description) >= 60:
        score += 15.0
    elif len(description) >= 20:
        score += 9.0
    elif description:
        score += 4.0

    if repo.archived:
        score *= 0.5

    return round(min(100.0, max(0.0, score)), 1)


def risk_score(repo: RepoData) -> float:
    """Risk puanı (0-100, yüksek = riskli): uzun süredir güncellenmeme,
    belirsiz lisans, az katkıcı ve deneysel işaretlere dayalı toplam."""

    score = 0.0

    age = days_since(repo.last_update)
    if age is None:
        score += 15.0
    elif age > 730:
        score += 45.0
    elif age > 365:
        score += 30.0
    elif age > 180:
        score += 15.0

    license_key = (repo.license or "").strip().lower()
    if license_key in UNCLEAR_LICENSES:
        score += 25.0

    if repo.contributors_count is not None:
        if repo.contributors_count <= 1:
            score += 20.0
        elif repo.contributors_count <= 3:
            score += 10.0
    else:
        score += 5.0  # bilinmiyor -> küçük temkinli ek puan

    text = f" {repo.name} {repo.description} ".lower()
    if any(keyword in text for keyword in EXPERIMENTAL_KEYWORDS):
        score += 15.0

    if repo.archived:
        score += 30.0

    return round(min(100.0, max(0.0, score)), 1)


def build_reason(repo: RepoData, quality: float, risk: float) -> str:
    """Puanları, kullanıcının tek bakışta anlayacağı kısa bir Türkçe
    gerekçe metnine çevirir."""

    positives: list[str] = []
    negatives: list[str] = []

    if repo.stars >= 1000:
        positives.append(f"{repo.stars:,} yıldız")

    age = days_since(repo.last_update)
    if age is not None and age <= 30:
        positives.append("son 30 günde aktif")
    elif age is not None and age > 365:
        negatives.append("1 yıldan uzun süredir güncellenmemiş")

    license_key = (repo.license or "").strip().lower()
    if license_key in PERMISSIVE_LICENSES:
        positives.append(f"izinli lisans ({repo.license})")
    elif license_key in UNCLEAR_LICENSES:
        negatives.append("lisans belirsiz/eksik")

    if repo.contributors_count is not None and repo.contributors_count <= 1:
        negatives.append("tek katkıcı")

    if repo.archived:
        negatives.append("arşivlenmiş (artık geliştirilmiyor)")

    parts: list[str] = []
    if positives:
        parts.append("Olumlu: " + ", ".join(positives))
    if negatives:
        parts.append("Riskli: " + ", ".join(negatives))
    if not parts:
        parts.append("Sınırlı veriyle nötr değerlendirme.")

    parts.append(f"Kalite {quality:.0f}/100, Risk {risk:.0f}/100.")
    return " | ".join(parts)
