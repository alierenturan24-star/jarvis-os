from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RepoData:
    """GitHub REST API'den toplanan ham repo verisi.

    ``GitHubIntelligence.search()`` bu tipi üretir; ``filter()`` ve
    ``score()`` bunun üzerinde çalışır. Kullanıcıya sunulan nihai çıktı
    değil, ara veri modelidir.
    """

    name: str
    full_name: str
    url: str
    description: str
    stars: int
    forks: int
    license: str
    last_update: str
    language: str
    category: str
    open_issues: int = 0
    archived: bool = False
    contributors_count: Optional[int] = None
    topics: list[str] = field(default_factory=list)
    readme_excerpt: Optional[str] = None


@dataclass
class RepoRecommendation:
    """Kullanıcıya sunulacak nihai, tek bir repo önerisi.

    ``GitHubIntelligence.recommend()`` çıktısı bu tipten bir listedir.
    """

    name: str
    url: str
    category: str
    quality_score: float
    risk_score: float
    license: str
    last_update: str
    reason: str
