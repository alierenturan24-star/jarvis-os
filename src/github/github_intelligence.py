from __future__ import annotations

from typing import Optional

from src.github.categories import SUPPORTED_CATEGORIES
from src.github.client import GitHubClient
from src.github.errors import GitHubIntelligenceError
from src.github.models import RepoData, RepoRecommendation
from src.github.scoring import build_reason, days_since, quality_score, risk_score

# GitHub'daki bazı repolar (bozuk/otomatik oluşturulmuş metadata) description
# alanında binlerce karakterlik ham sayfa/dosya dökümü taşıyabiliyor (ör.
# GitHub arayüzünün HTML metnini veya bir config dosyasının tamamını içeren
# repolar — Sprint 9 kabul testinde gözlemlendi). Bu, hem puanlamayı
# çarpıtabilir hem de gereksiz bellek/işlem yükü yaratır; bu yüzden
# ``_to_repo_data`` açıklamayı burada güvenli bir üst sınıra keser.
MAX_DESCRIPTION_LENGTH = 500


class GitHubIntelligence:
    """Açık kaynak AI projelerini GitHub üzerinde arayıp değerlendiren,
    salt-okunur (read-only) araştırma katmanı.

    Bu sınıf yalnızca ARAŞTIRMA yapar: hiçbir repoyu klonlamaz, indirmez
    veya JARVIS'in geri kalanına entegre etmez (Sprint 9 kapsamı). Nihai
    çıktısı, kullanıcıya sunulacak ``RepoRecommendation`` listesidir.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        client: Optional[GitHubClient] = None,
        fetch_contributors: bool = True,
    ) -> None:
        self.client = client or GitHubClient(token=token)
        self.fetch_contributors = fetch_contributors

    # --- Arama ---------------------------------------------------------

    def search(
        self,
        category: str,
        max_results: int = 10,
        min_stars: int = 0,
        fetch_readme: bool = False,
    ) -> list[RepoData]:
        """Verilen kategori için GitHub'da açık kaynak repo arar.

        ``category``, desteklenen 10 aramadan biri olmalıdır (ör.
        "ai agent", "llm", "mcp server" — bkz. ``SUPPORTED_CATEGORIES``);
        değilse ``GitHubIntelligenceError`` fırlatılır.

        ``fetch_readme=True`` verilirse her repo için ek bir API isteğiyle
        README'nin ilk bölümü de toplanır (alaka değerlendirmesinde
        kullanılır — bkz. ``src.evaluation``); varsayılan ``False``dır
        çünkü rate limit bütçesini repo başına 1 istek daha tüketir ve
        mevcut çağıranların davranışını DEĞİŞTİRMEMESİ gerekir.
        """

        key = category.strip().lower()

        if key not in SUPPORTED_CATEGORIES:
            supported = ", ".join(sorted(SUPPORTED_CATEGORIES))
            raise GitHubIntelligenceError(
                f"Desteklenmeyen arama kategorisi: {category!r}. "
                f"Desteklenenler: {supported}"
            )

        max_results = max(1, min(max_results, 50))
        query = SUPPORTED_CATEGORIES[key]
        if min_stars > 0:
            query = f"{query} stars:>={min_stars}"

        # Sprint 23 (Sprint 22 kök sebep analizine göre): sabit sort=stars,
        # GitHub'ın kendi relevance/best-match sıralamasını devre dışı
        # bırakıp jenerik kategori sorgularında (ör. "ai agent") konuyla
        # ilgisiz ama astronomik yıldızlı "awesome list" repolarını
        # (sindresorhus/awesome, public-apis, ...) öne çıkarıyordu (canlı
        # doğrulandı, bkz. Sprint 22 raporu). Yalnızca çağıran GERÇEKTEN bir
        # yıldız eşiği istediğinde (``min_stars`` > 0 -- mevcut parametre,
        # yeni bir şey EKLENMEDİ) yıldıza göre sıralamak anlamlı; aksi
        # halde GitHub'ın varsayılan best-match sıralamasına bırakılır.
        params = {
            "q": query,
            "per_page": min(max_results, 30),
        }
        if min_stars > 0:
            params["sort"] = "stars"
            params["order"] = "desc"

        try:
            payload = self.client.get(
                "/search/repositories",
                params=params,
            )
        except GitHubIntelligenceError:
            raise
        except Exception as error:  # beklenmeyen (ağ/parse dışı) hatalar
            raise GitHubIntelligenceError(f"GitHub araması başarısız: {error}") from error

        items = payload.get("items", []) if isinstance(payload, dict) else []
        repos = [self._to_repo_data(item, category=key) for item in items[:max_results]]

        if self.fetch_contributors:
            for repo in repos:
                repo.contributors_count = self.client.get_contributor_count(repo.full_name)

        if fetch_readme:
            for repo in repos:
                repo.readme_excerpt = self.client.get_readme_excerpt(repo.full_name)

        return repos

    @staticmethod
    def _to_repo_data(item: dict, category: str) -> RepoData:
        license_info = item.get("license") or {}
        description = str(item.get("description") or "")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            description = description[:MAX_DESCRIPTION_LENGTH].rstrip() + "…"

        topics = item.get("topics") or []
        topics = [str(t) for t in topics] if isinstance(topics, list) else []

        return RepoData(
            name=str(item.get("name", "")),
            full_name=str(item.get("full_name", "")),
            url=str(item.get("html_url", "")),
            description=description,
            stars=int(item.get("stargazers_count", 0) or 0),
            forks=int(item.get("forks_count", 0) or 0),
            license=str(license_info.get("spdx_id") or license_info.get("key") or ""),
            last_update=str(item.get("pushed_at") or item.get("updated_at") or ""),
            language=str(item.get("language") or ""),
            category=category,
            open_issues=int(item.get("open_issues_count", 0) or 0),
            archived=bool(item.get("archived", False)),
            topics=topics,
        )

    # --- Filtreleme ------------------------------------------------------

    def filter(
        self,
        repos: list[RepoData],
        *,
        min_stars: int = 0,
        max_age_days: Optional[int] = None,
        require_license: bool = False,
        exclude_archived: bool = True,
    ) -> list[RepoData]:
        """Toplanan repoları basit kalite eşiklerine göre eler."""

        filtered = []

        for repo in repos:
            if repo.stars < min_stars:
                continue
            if require_license and not repo.license:
                continue
            if exclude_archived and repo.archived:
                continue
            if max_age_days is not None:
                age = days_since(repo.last_update)
                if age is not None and age > max_age_days:
                    continue
            filtered.append(repo)

        return filtered

    # --- Puanlama --------------------------------------------------------

    def score(self, repo: RepoData) -> tuple[float, float]:
        """Bir repo için ``(quality_score, risk_score)`` çiftini hesaplar."""

        return quality_score(repo), risk_score(repo)

    # --- Öneri -------------------------------------------------------------

    def recommend(
        self,
        category: str,
        max_results: int = 10,
        min_stars: int = 0,
        max_age_days: Optional[int] = None,
        require_license: bool = False,
    ) -> list[RepoRecommendation]:
        """Uçtan uca akış: ``search`` -> ``filter`` -> ``score`` ->
        ``RepoRecommendation`` listesi (kalite puanına göre yüksekten
        düşüğe sıralı). Klonlama/indirme/entegrasyon YAPMAZ — yalnızca
        rapor için veri üretir."""

        repos = self.search(category, max_results=max_results, min_stars=min_stars)
        repos = self.filter(
            repos,
            min_stars=min_stars,
            max_age_days=max_age_days,
            require_license=require_license,
        )

        recommendations: list[RepoRecommendation] = []

        for repo in repos:
            quality, risk = self.score(repo)
            recommendations.append(
                RepoRecommendation(
                    name=repo.name,
                    url=repo.url,
                    category=repo.category,
                    quality_score=quality,
                    risk_score=risk,
                    license=repo.license or "belirtilmemiş",
                    last_update=repo.last_update,
                    reason=build_reason(repo, quality, risk),
                )
            )

        recommendations.sort(key=lambda rec: (-rec.quality_score, rec.risk_score))
        return recommendations
