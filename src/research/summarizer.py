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

        selected = compact_results(results, limit=6)
        source_blocks = []
        for index, result in enumerate(selected, start=1):
            source_blocks.append(
                f"Kaynak {index}\n"
                f"Platform: {result.get('source', 'Web')}\n"
                f"Başlık: {result.get('title', '')}\n"
                f"Adres: {result.get('url', '')}\n"
                f"Bilgi: {result.get('summary', '')}"
            )

        prompt = f"""
Sen JARVIS Araştırma Departmanısın.

Araştırma konusu: {topic}

Toplanan sonuçlar:
{"\n\n".join(source_blocks)}

{TURKISH_OUTPUT_POLICY}

Görev:
- Yalnızca verilen kaynaklara dayan.
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
        return source_fallback(topic, selected, limit=6) if is_llm_failure(answer) else answer
