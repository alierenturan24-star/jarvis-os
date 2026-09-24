from src.providers.provider_manager import TASK_LONG_RESEARCH
from src.providers.router import ModelRouter
from src.utils.language_policy import TURKISH_OUTPUT_POLICY
from src.utils.llm_utils import compact_results, is_llm_failure, source_fallback


class Summarizer:
    def __init__(self) -> None:
        self.router = ModelRouter()
        # Sprint 25 (Intelligent Provider Router): son yönlendirme kararının
        # dökümü (hangi provider seçildi/kullanıldı, neden, fallback oldu mu,
        # süre) -- dış arayüz/davranış DEĞİŞMEDİ, yalnızca gözlemlenebilirlik
        # için.
        self.last_route = None

    def summarize(self, topic: str, results: list[dict], preferred_provider: str | None = None) -> str:
        if not results:
            return "Özetlenecek güvenilir araştırma sonucu bulunamadı."

        # Keep factual/current evidence and format-only video references in
        # separate buckets.  A straight first-N truncation used to consume
        # all slots with DE/FR/IT news rows, so the downstream planner never
        # saw the genuinely found public video references.
        factual_results = [row for row in results if row.get("reference_role") != "format_only"]
        format_results = [row for row in results if row.get("reference_role") == "format_only"]
        selected = compact_results(factual_results, limit=8) + compact_results(format_results, limit=2)
        source_blocks = []
        for index, result in enumerate(selected, start=1):
            source_blocks.append(
                f"Kaynak {index}\n"
                f"Platform: {result.get('source', 'Web')}\n"
                f"Başlık: {result.get('title', '')}\n"
                f"Adres: {result.get('url', '')}\n"
                f"Yayın tarihi: {result.get('published_at', '')}\n"
                f"Kaynak dili: {result.get('source_language', '')}\n"
                f"Yayıncı: {result.get('publisher', '')}\n"
                f"Referans rolü: {result.get('reference_role', 'factual')}\n"
                f"Video süresi: {result.get('duration', '')}\n"
                f"Etkileşim metadatası: {result.get('statistics', {})}\n"
                f"Bilgi: {result.get('summary', '')}"
            )

        source_text = "\n\n".join(source_blocks)

        prompt = f"""
Sen JARVIS Araştırma Departmanısın.

Araştırma konusu: {topic}

Toplanan sonuçlar:
{source_text}

{TURKISH_OUTPUT_POLICY}

Görev:
- Yalnızca verilen kaynaklara dayan.
- "format_only" rolündeki video referanslarını güncel haber/faktüel kanıt sayma. Bunlardan yalnızca
  soyut hook, tempo, merak açığı, anlatı sırası ve başlık kalıbı öğren; başlığı, metni, kapağı,
  sesi, görüntüyü veya videoyu kopyalama.
- Güncel bir istekse genel ana sayfayı güncellik kanıtı sayma; yalnızca açık yayın tarihli makaleleri kullan.
- İstenen kaynak dillerinin her birini ayrı ayrı kontrol et; eksik dil veya tarih varsa açıkça belirt.
- İlk satırda "SEÇİLEN KONU:" ile tek, somut ve kaynaklarla desteklenen konuyu yaz.
- Seçimi destekleyen makalelerin başlık, yayın tarihi, kaynak dili ve tam adresini göster; tarih/URL uydurma.
- Ortak ve önemli noktaları birleştir.
- Çelişki veya belirsizlik varsa açıkça belirt.
- Kullanıcı açısından somut faydayı değerlendir.
- Son başlık "JARVIS Önerisi" olsun.
- En fazla 400 kelime kullan.

Araştırma raporu:
"""
        # Sprint 25 düzeltmesi: "Research -> Ollama sabit" kaldırıldı.
        # Provider artık ProviderManager'ın görev-türü karar tablosuna göre
        # seçiliyor (araştırma/uzun sentez -> AIMLAPI, başarısız olursa
        # OTOMATİK olarak Ollama'ya düşer -- bkz. route_and_generate).
        # Sprint 35: ``preferred_provider`` doluysa (AI Strategy Engine bir
        # karar verdiyse) route_and_generate buna öncelik verir; boşsa
        # davranış BİREBİR eskisi gibidir.
        self.last_route = self.router.manager.route_and_generate(
            prompt=prompt, task_type=TASK_LONG_RESEARCH, preferred_provider=preferred_provider,
        )
        answer = self.last_route.output
        return source_fallback(topic, selected, limit=10) if is_llm_failure(answer) else answer
