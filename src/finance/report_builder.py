from datetime import datetime
from pathlib import Path
import re


class FinanceReportBuilder:

    # Sprint 38'de research/report_builder.py'de yakalanan Windows MAX_PATH
    # (260 karakter) hatasının AYNISI ("[Errno 22] Invalid argument") --
    # Sprint 39 canlı testinde finance için de tetiklendi (uzun bir istek
    # metni ham "asset" olarak dosya adına geçince). Aynı, kanıtlanmış
    # düzeltme: dosya adı burada da güvenli bir uzunlukta kesiliyor.
    _MAX_FILENAME_TOPIC_LENGTH = 80

    def __init__(self) -> None:

        self.folder = Path("workspace") / "finance"

        self.folder.mkdir(
            parents=True,
            exist_ok=True,
        )

    @staticmethod
    def _safe_filename(text: str) -> str:

        filename = text.casefold().strip()
        filename = re.sub(r"[^\w\s-]", "", filename)
        filename = re.sub(r"[\s-]+", "_", filename)
        filename = filename[:FinanceReportBuilder._MAX_FILENAME_TOPIC_LENGTH].rstrip("_")

        return filename or "finance"

    def save(
        self,
        asset: str,
        analysis: str,
        risk_score: int,
        opportunity_score: int,
        sentiment_score: int,
        results: list[dict],
    ) -> Path:

        timestamp = datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )

        path = self.folder / (
            f"{self._safe_filename(asset)}_{timestamp}.md"
        )

        sources = []

        for index, item in enumerate(results, start=1):

            sources.append(
                f"""### {index}. {item.get("title", "Başlıksız kaynak")}

- Adres: {item.get("url", "")}
- Bilgi: {item.get("summary", "")}
"""
            )

        content = f"""# {asset} Finans Analizi

## Tarih

{datetime.now().strftime("%d.%m.%Y %H:%M")}

## Puanlar

- Risk: {risk_score}/100
- Fırsat: {opportunity_score}/100
- Haber duyarlılığı: {sentiment_score}/100

## JARVIS Analizi

{analysis}

## Kaynaklar

{"".join(sources)}

## Güvenlik Notu

Bu rapor yatırım tavsiyesi değildir.
Otomatik emir veya para transferi yapılmamıştır.
Gerçek işlem öncesinde kullanıcı onayı ve bağımsız kontrol gerekir.
"""

        path.write_text(
            content,
            encoding="utf-8",
        )

        return path