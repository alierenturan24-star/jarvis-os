from datetime import datetime
from pathlib import Path


class OpportunityReportBuilder:

    def __init__(self) -> None:

        self.folder = (
            Path("workspace")
            / "opportunity"
        )

        self.folder.mkdir(
            parents=True,
            exist_ok=True,
        )

    def save(
        self,
        summary: str,
        opportunities: list[dict],
    ) -> Path:

        timestamp = datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )

        path = self.folder / (
            f"opportunity_report_{timestamp}.md"
        )

        sections = []

        for index, item in enumerate(
            opportunities,
            start=1,
        ):

            sections.append(
                f"""## {index}. {item.get("title", "Başlıksız fırsat")}

- Genel puan: {item.get("score", 0)}/100
- Hedef uyumu: {item.get("relevance", 0)}/100
- Erişilebilirlik: {item.get("accessibility", 0)}/100
- Maliyet avantajı: {item.get("cost_advantage", 0)}/100
- Gelir potansiyeli: {item.get("income_potential", 0)}/100
- Risk: {item.get("risk", 0)}/100
- Adres: {item.get("url", "")}

{item.get("summary", "")}
"""
            )

        content = f"""# JARVIS Fırsat Raporu

## Tarih

{datetime.now().strftime("%d.%m.%Y %H:%M")}

## JARVIS Değerlendirmesi

{summary}

## Puanlanan Fırsatlar

{"".join(sections)}

## Güvenlik Notu

Bu rapor araştırma ve karar desteği içindir.
Garanti kazanç anlamına gelmez.
Ödeme, üyelik, hesap açma veya finansal işlem
kullanıcı onayı olmadan yapılmamalıdır.
"""

        path.write_text(
            content,
            encoding="utf-8",
        )

        return path