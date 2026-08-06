from datetime import datetime
from pathlib import Path
import re

from src.github.models import RepoRecommendation


class GitHubReportBuilder:
    """``GitHubIntelligence.recommend()`` çıktısını okunabilir bir
    Markdown raporuna dönüştürüp diske kaydeder.

    Sprint 9 kapsamı yalnızca RAPORLAMA'dır: burada hiçbir repo
    klonlanmaz/indirilmez, mevcut araştırma akışına (``ResearchManager``)
    entegre edilmez — bağımsız, katmanlar arası bir yardımcıdır.
    """

    def __init__(self) -> None:

        self.folder = Path("workspace") / "research" / "github"

        self.folder.mkdir(
            parents=True,
            exist_ok=True,
        )

    @staticmethod
    def _safe_filename(category: str) -> str:

        filename = category.casefold().strip()
        filename = re.sub(r"[^\w\s-]", "", filename)
        filename = re.sub(r"[\s-]+", "_", filename)

        return filename or "github_arama"

    def save(
        self,
        category: str,
        recommendations: list[RepoRecommendation],
    ) -> Path:

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        filename = (
            f"{self._safe_filename(category)}_"
            f"{timestamp}.md"
        )

        path = self.folder / filename

        blocks = []

        for index, rec in enumerate(recommendations, start=1):

            blocks.append(
                f"""
### {index}. {rec.name}

- Adres: {rec.url}
- Kategori: {rec.category}
- Kalite Puanı: {rec.quality_score}/100
- Risk Puanı: {rec.risk_score}/100
- Lisans: {rec.license}
- Son Güncelleme: {rec.last_update}
- Değerlendirme: {rec.reason}
""".strip()
            )

        body = "\n\n".join(blocks) if blocks else "Kriterlere uyan repo bulunamadı."

        content = f"""# GitHub Zekası Raporu: {category}

## Tarih

{datetime.now().strftime("%d.%m.%Y %H:%M")}

## Bulunan Repo Sayısı

{len(recommendations)}

## Öneriler

{body}
"""

        path.write_text(
            content,
            encoding="utf-8",
        )

        return path
