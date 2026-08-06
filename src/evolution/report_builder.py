from datetime import datetime
from pathlib import Path


class EvolutionReportBuilder:
    def __init__(self) -> None:
        self.folder = Path("workspace") / "evolution"
        self.folder.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        focus: str,
        evaluation: str,
        proposals: list[dict],
    ) -> Path:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = self.folder / f"evolution_report_{timestamp}.md"

        sections: list[str] = []
        for index, item in enumerate(proposals, start=1):
            sections.append(
                f"""## {index}. {item.get('title', 'Başlıksız öneri')}

- Genel puan: {item.get('score', 0)}/100
- Hedef uyumu: {item.get('goal_fit', 0)}/100
- Güvenlik: {item.get('safety', 0)}/100
- Uygulama kolaylığı: {item.get('implementation_ease', 0)}/100
- Maliyet avantajı: {item.get('cost_advantage', 0)}/100
- Beklenen değer: {item.get('expected_value', 0)}/100
- Kaynak: {item.get('url', '')}

{item.get('summary', '')}
"""
            )

        content = f"""# JARVIS Kontrollü Gelişim Raporu

## Tarih

{datetime.now().strftime('%d.%m.%Y %H:%M')}

## Odak

{focus or 'Genel JARVIS gelişimi'}

## JARVIS Değerlendirmesi

{evaluation}

## Gelişim Adayları

{''.join(sections)}

## Değişmez Güvenlik Kuralı

Bu rapor yalnızca araştırma ve geliştirme önerisidir.
JARVIS kendi çekirdek kodunu, hesap ayarlarını, API anahtarlarını veya
finansal işlemleri kullanıcı onayı olmadan değiştirmez. İnternetten bulunan
kod doğrudan çalıştırılmaz; önce inceleme, izole test ve açık onay gerekir.
"""
        path.write_text(content, encoding="utf-8")
        return path
