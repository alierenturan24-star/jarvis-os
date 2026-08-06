from src.evolution.collector import EvolutionCollector
from src.evolution.report_builder import EvolutionReportBuilder
from src.evolution.scorer import EvolutionScorer
from src.experience.experience import Experience
from src.experience.experience_manager import ExperienceManager
from src.providers.router import ModelRouter


class EvolutionManager:
    """JARVIS için kontrollü öğrenme ve gelişim önerileri üretir."""

    def __init__(self) -> None:
        self.collector = EvolutionCollector()
        self.scorer = EvolutionScorer()
        self.report_builder = EvolutionReportBuilder()
        self.experience = ExperienceManager()
        self.router = ModelRouter()

    def _build_fallback(self, proposals: list[dict]) -> str:
        lines = [
            "Model özeti üretilemedi; puanlama motorunun en güçlü adayları:",
        ]
        for index, item in enumerate(proposals[:5], start=1):
            lines.append(
                f"{index}. {item.get('title', 'Başlıksız')} "
                f"({item.get('score', 0)}/100)"
            )
        lines.append(
            "Hiçbir öneri otomatik uygulanmadı. Önce inceleme ve test gerekir."
        )
        return "\n".join(lines)

    def _evaluate(self, focus: str, proposals: list[dict]) -> str:
        compact = proposals[:5]
        blocks = []

        for index, item in enumerate(compact, start=1):
            blocks.append(
                f"""Aday {index}
Başlık: {item.get('title', '')}
Açıklama: {item.get('summary', '')[:500]}
Kaynak: {item.get('url', '')}
Puan: {item.get('score', 0)}/100
Güvenlik: {item.get('safety', 0)}/100
"""
            )

        prompt = f"""
Sen JARVIS Kontrollü Gelişim Departmanı yöneticisisin.

Odak:
{focus or 'JARVIS sistemini güvenli, modüler ve yararlı şekilde geliştirmek'}

Adaylar:
{''.join(blocks)}

Zorunlu kurallar:
- Cevabın tamamı doğal ve anlaşılır Türkçe olsun.
- Yalnızca verilen adaylara dayan.
- En fazla üç öneriyi önceliklendir.
- Her öneri için fayda, risk ve güvenli ilk test adımını yaz.
- İnternetten kod indirip doğrudan çalıştırmayı önerme.
- Çekirdek kodu otomatik değiştirme önerme.
- Üyelik, ödeme, hesap veya API anahtarı gereksinimini açıkça belirt.
- Kullanıcı onayı olmadan hiçbir değişikliğin uygulanmayacağını belirt.
- Kısa ve somut yaz.

Değerlendirme:
"""

        answer = self.router.generate(
            prompt=prompt,
            provider_name="ollama",
        )

        failed_markers = (
            "zaman aşımına uğradı",
            "ollama bulunamadı",
            "ollama hata verdi",
            "model cevap üretmedi",
        )
        if not answer or any(marker in answer.casefold() for marker in failed_markers):
            return self._build_fallback(proposals)
        return answer

    def scan(self, focus: str = "") -> str:
        print("[Evolution] JARVIS gelişim fırsatları taranıyor...")

        collected = self.collector.collect(focus=focus)
        if not collected:
            return "JARVIS gelişimi için güncel aday bulunamadı."

        proposals = self.scorer.rank(collected, limit=8)
        evaluation = self._evaluate(focus, proposals)
        report_path = self.report_builder.save(
            focus=focus,
            evaluation=evaluation,
            proposals=proposals,
        )

        self.experience.save(
            Experience(
                name="evolution_scan",
                version="1.0",
                success=True,
                score=proposals[0].get("score", 0) if proposals else 0,
                notes=(
                    f"{len(collected)} aday incelendi; "
                    f"{len(proposals)} öneri raporlandı. "
                    "Otomatik değişiklik yapılmadı."
                ),
            )
        )

        return (
            "Kontrollü gelişim taraması tamamlandı.\n\n"
            f"{evaluation}\n\n"
            f"İncelenen aday: {len(collected)}\n"
            f"Rapora alınan öneri: {len(proposals)}\n"
            "Otomatik değişiklik: YAPILMADI\n"
            f"Rapor kaydedildi:\n{report_path}"
        )
