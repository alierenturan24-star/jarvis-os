from src.opportunity.collector import OpportunityCollector
from src.opportunity.report_builder import OpportunityReportBuilder
from src.opportunity.scorer import OpportunityScorer
from src.providers.router import ModelRouter
from src.utils.language_policy import TURKISH_OUTPUT_POLICY
from src.utils.llm_utils import compact_results, is_llm_failure


class OpportunityManager:
    def __init__(self) -> None:
        self.collector = OpportunityCollector()
        self.scorer = OpportunityScorer()
        self.report_builder = OpportunityReportBuilder()
        self.router = ModelRouter()

    @staticmethod
    def _fallback(opportunities: list[dict]) -> str:
        lines = [
            "Yerel model zamanında yanıt veremediği için puanlama motorunun özeti gösteriliyor.",
            "",
            "Öncelikli fırsatlar:",
        ]
        for index, item in enumerate(opportunities[:5], start=1):
            lines.append(
                f"{index}. {item.get('title', 'Başlıksız fırsat')} — "
                f"puan {item.get('score', 0)}/100, risk {item.get('risk', 0)}/100"
            )
            if item.get("url"):
                lines.append(f"   Adres: {item['url']}")
        lines.extend([
            "",
            "JARVIS Önerisi: Üyelik veya ödeme yapmadan önce ilk iki seçeneğin resmî sayfalarını doğrula.",
        ])
        return "\n".join(lines)

    def _summarize(self, opportunities: list[dict]) -> str:
        selected = compact_results(opportunities, limit=5)
        blocks = []
        for index, item in enumerate(selected, start=1):
            blocks.append(
                f"Fırsat {index}\n"
                f"Başlık: {item.get('title', '')}\n"
                f"Adres: {item.get('url', '')}\n"
                f"Bilgi: {item.get('summary', '')}\n"
                f"Puan: {item.get('score', 0)}/100\n"
                f"Risk: {item.get('risk', 0)}/100"
            )

        prompt = f"""
Sen JARVIS Fırsat Departmanı yöneticisisin.

Kullanıcının hedefleri:
- JARVIS sistemini geliştirmek
- Düşük maliyetli yapay zekâ araçlarını kullanmak
- İçerik ve iş otomasyonu kurmak
- Gerçekçi gelir fırsatları bulmak
- Finansal riski sınırlamak

Puanlanan fırsatlar:
{"\n\n".join(blocks)}

{TURKISH_OUTPUT_POLICY}

Görev:
- En değerli en fazla beş fırsatı sırala.
- Her biri için fayda, ilk güvenli adım, ücret durumu ve temel riski açıkla.
- Doğrulanmamış ücretsiz kredi veya kampanya iddiasını kesin gerçek gibi yazma.
- Garanti gelir iddiasında bulunma.
- En fazla 400 kelime kullan.

Değerlendirme:
"""
        answer = self.router.generate(prompt=prompt, provider_name="ollama")
        return self._fallback(opportunities) if is_llm_failure(answer) else answer

    def scan(self, topic: str = "") -> str:
        print("[Opportunity] Fırsatlar taranıyor...")
        collected = self.collector.collect(topic=topic)
        if not collected:
            return "Fırsat araştırmasında sonuç bulunamadı."

        ranked = self.scorer.rank(opportunities=collected, limit=10)
        summary = self._summarize(ranked)
        report_path = self.report_builder.save(summary=summary, opportunities=ranked)

        return (
            "Fırsat araştırması tamamlandı.\n\n"
            f"{summary}\n\n"
            f"İncelenen sonuç: {len(collected)}\n"
            f"Rapora alınan fırsat: {len(ranked)}\n"
            f"Rapor kaydedildi:\n{report_path}"
        )
