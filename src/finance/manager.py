from src.finance.collector import FinanceCollector
from src.finance.report_builder import FinanceReportBuilder
from src.finance.risk_engine import FinanceRiskEngine
from src.providers.router import ModelRouter
from src.utils.language_policy import TURKISH_OUTPUT_POLICY
from src.utils.llm_utils import compact_results, is_llm_failure, source_fallback


class FinanceManager:
    def __init__(self) -> None:
        self.collector = FinanceCollector()
        self.risk_engine = FinanceRiskEngine()
        self.report_builder = FinanceReportBuilder()
        self.router = ModelRouter()

    def analyze(self, asset: str, preferred_provider: str | None = None) -> str:
        asset = asset.strip()
        if not asset:
            return "Analiz edilecek varlık belirtilmedi."

        print(f"[Finance] {asset} analiz ediliyor...")
        results = self.collector.collect(asset)
        if not results:
            return "Finans araştırması için kaynak bulunamadı."

        risk = self.risk_engine.analyze(results)
        selected = compact_results(results, limit=5)
        source_text = "\n\n".join(
            (
                f"Kaynak {index}\n"
                f"Başlık: {item.get('title', '')}\n"
                f"Bilgi: {item.get('summary', '')}\n"
                f"Adres: {item.get('url', '')}"
            )
            for index, item in enumerate(selected, start=1)
        )

        prompt = f"""
Sen JARVIS Finans Departmanı analistisin.

İncelenen varlık: {asset}

Kaynaklar:
{source_text}

Hesaplanan gösterge puanları:
- Risk: {risk.risk_score}/100
- Fırsat: {risk.opportunity_score}/100
- Haber duyarlılığı: {risk.sentiment_score}/100

{TURKISH_OUTPUT_POLICY}

Görev:
1. Kaynaklarda açıkça görülen olumlu gelişmeleri yaz.
2. Kaynaklarda açıkça görülen olumsuz gelişmeleri ve riskleri yaz.
3. İzlenmesi gereken en fazla üç gelişmeyi belirt.
4. Fiyat veya getiri uydurma; kesin alım-satım emri verme.
5. Son bölümün başlığı "JARVIS Değerlendirmesi" olsun.
6. En fazla 350 kelime kullan.

Finans raporu:
"""

        # Sprint 35: varsayılan hâlâ "ollama" (davranış BİREBİR eskisi
        # gibi) -- AI Strategy Engine'in seçtiği provider yalnızca
        # GERÇEKTEN kullanılabilirse devreye girer (yeni bir provider
        # routing İCAT EDİLMEDİ, mevcut ``ProviderManager.get().
        # is_available()`` kullanıldı).
        provider_name = self._resolve_provider(preferred_provider)

        # Sprint 40: Research'ün (Summarizer) zaten kullandığı
        # ``route_and_generate``'e geçildi -- düz ``generate()`` yerine,
        # otomatik Ollama fallback'i ve çağrı geçmişi kaydını (bkz.
        # ``src.providers.execution_history``) ÜCRETSİZ kazanır; yeni bir
        # fallback mantığı İCAT EDİLMEDİ.
        route_result = self.router.manager.route_and_generate(
            prompt=prompt, task_type="finance", preferred_provider=provider_name,
        )
        analysis = route_result.output
        if is_llm_failure(analysis):
            analysis = source_fallback(asset, selected, limit=5)
        elif route_result.fallback_used:
            analysis += (
                f"\n\n(Not: birincil sağlayıcı ({route_result.chosen_provider}) başarısız oldu, "
                f"otomatik olarak {route_result.provider_used}'a geçildi.)"
            )

        report_path = self.report_builder.save(
            asset=asset,
            analysis=analysis,
            risk_score=risk.risk_score,
            opportunity_score=risk.opportunity_score,
            sentiment_score=risk.sentiment_score,
            results=results,
        )

        return (
            "Finans analizi tamamlandı.\n\n"
            f"Risk: {risk.risk_score}/100\n"
            f"Fırsat: {risk.opportunity_score}/100\n"
            f"Haber duyarlılığı: {risk.sentiment_score}/100\n\n"
            f"{analysis}\n\n"
            f"Rapor kaydedildi:\n{report_path}"
        )

    def _resolve_provider(self, preferred_provider: str | None) -> str:
        """Sprint 35: AI Strategy Engine'in seçtiği provider'ı yalnızca
        GERÇEKTEN kullanılabilirse kullanır; aksi halde (veya hiç
        verilmediyse) mevcut "ollama" varsayılanına düşer -- davranış
        eskisiyle BİREBİR uyumlu kalır."""

        if not preferred_provider:
            return "ollama"

        candidate = self.router.manager.get(preferred_provider)
        if candidate is not None and candidate.is_available():
            return preferred_provider

        return "ollama"
