from __future__ import annotations

from typing import Optional

from src.providers.router import ModelRouter
from src.research.local_code_search import (
    detect_referenced_symbols,
    format_evidence,
    gather_code_evidence,
)
from src.utils.language_policy import TURKISH_OUTPUT_POLICY
from src.utils.llm_utils import is_llm_failure

# Sprint 41 (LOCAL CODE INTELLIGENCE): JARVIS'in kendi proje kodu/mimarisi
# hakkındaki sorulara -- ``ResearchManager`` (gerçek WEB araması) YERİNE --
# yalnızca YEREL dosyalardan toplanmış kanıtla cevap verir. ``FinanceManager``/
# ``MediaManager`` ile AYNI desen: tool-first kanıt toplama + TEK bir LLM
# sentez çağrısı (``ModelRouter``/``route_and_generate`` üzerinden, ZATEN
# VAR OLAN provider seçim mantığı). İnternete HİÇ dokunmaz.

# Sprint 44 (CLAUDE CODE WORKER BRIDGE bölüm 7/10): Claude Code'u YALNIZCA
# GERÇEKTEN karmaşık coding/debugging/mimari/büyük-refactor/test-hatası
# görevlerinde ADAY yapan dar, açık bir sinyal kümesi -- basit "X sınıfını
# incele" soruları BUNA GİRMEZ (TEST I). Yeni bir sınıflandırma sistemi İCAT
# EDİLMEDİ -- ZATEN VAR OLAN keyword-tabanlı sezgisel desenle (bkz.
# ``CostOptimizer.classify``, ``detect_mission_type``) AYNI yaklaşım.
_COMPLEX_CODING_SIGNALS = (
    "debug", "hata ayıkla", "mimari", "architecture", "büyük refactor",
    "refactor", "test başarısız", "test failure", "test hatası",
    "neden çalışmıyor", "neden bozuluyor", "kırıldı", "bug'ı düzelt",
    "bug fix", "hatayı düzelt", "kökten çöz", "root cause",
)


def is_complex_coding_query(query: str) -> bool:
    """Sprint 44 bölüm 7/10: Claude Code'u YALNIZCA gerçekten karmaşık
    coding/debugging/mimari görevlerinde ADAY yapar -- Strategy'nin
    (burada: bu sınıflandırmanın KENDİSİ) gerçekten uygun görmediği hiçbir
    görevde worker çağrılmaz (bölüm 10: "Claude kendi kendine
    çağrılmasın")."""

    lowered = (query or "").casefold()
    return any(signal in lowered for signal in _COMPLEX_CODING_SIGNALS)


class LocalCodeManager:
    def __init__(self) -> None:
        self.router = ModelRouter()

    def analyze(self, query: str, preferred_provider: Optional[str] = None) -> str:
        query = (query or "").strip()
        if not query:
            return "İncelenecek konu belirtilmedi."

        print(f"[LocalCode] '{query}' için yerel proje kodu inceleniyor (internet KULLANILMIYOR)...")

        symbols = detect_referenced_symbols(query)
        evidence = gather_code_evidence(symbols)
        evidence_text = format_evidence(evidence)

        if not evidence:
            return (
                "Yerel kod analizi: metinde JARVIS'in kendi kod tabanında bilinen bir "
                "sınıf/modül adı bulunamadı -- internet ARANMADI, uydurma bir cevap da "
                "ÜRETİLMEDİ. Daha spesifik bir sınıf/modül adı belirtirseniz (ör. "
                "'CostOptimizer') tekrar denenebilir."
            )

        prompt = f"""
Sen JARVIS'in kendi kod tabanını inceleyen bir yerel kod analiz departmanısın.

Kullanıcının sorusu: {query}

{evidence_text}

{TURKISH_OUTPUT_POLICY}

Görev:
- Yalnızca YUKARIDAKİ kanıtlara dayan -- internet KULLANILMADI, kanıtların
  dışında bir bilgi UYDURMA.
- Hangi sınıf/modül hangi dosyada, birbirleriyle nasıl ilişkili
  (import/çağrı/kullanım) olduğunu KANITLARDAN çıkar.
- Emin olmadığın bir bağlantıyı KESİNMİŞ gibi sunma, belirsizse açıkça belirt.
- Kısa ve somut yaz.
"""

        provider_name = self._resolve_provider(preferred_provider, query)
        route_result = self.router.manager.route_and_generate(
            prompt=prompt, task_type="coding", preferred_provider=provider_name,
        )
        analysis = route_result.output

        if is_llm_failure(analysis):
            return (
                "Yerel kod kanıtları toplandı ama sentez üretilemedi (model yanıt vermedi).\n\n"
                f"{evidence_text}"
            )

        if route_result.fallback_used:
            analysis += (
                f"\n\n(Not: birincil sağlayıcı ({route_result.chosen_provider}) başarısız oldu, "
                f"otomatik olarak {route_result.provider_used}'a geçildi.)"
            )

        return (
            "Yerel kod analizi tamamlandı (internet KULLANILMADI).\n\n"
            f"{analysis}\n\n"
            f"{evidence_text}"
        )

    def _resolve_provider(self, preferred_provider: Optional[str], query: str = "") -> str:
        """``FinanceManager``/``MediaManager._resolve_provider`` ile AYNI
        temel desen + Sprint 44: sorgu GERÇEKTEN karmaşık bir coding/
        debugging görevi sinyali taşıyorsa VE Claude Code CLI kullanılabilir
        durumdaysa, ona öncelik verilir. AI Strategy'nin (CostOptimizer)
        Claude Code'dan hiç HABERİ olmadığı için (bkz. Sprint 44 audit) bu,
        önceden verilmiş bir kararı EZMEZ -- yalnızca Strategy'nin
        göremediği bir seçeneği ekler. ``route_and_generate``'in
        ``preferred_provider`` parametresi zaten "kullanılamıyorsa görev-
        türü tablosuna düş" mantığını İÇERDİĞİ için (bkz. provider_manager.
        py), Claude Code kullanılamıyorsa buradaki eski davranış AYNEN
        korunur -- yeni bir fallback mimarisi İCAT EDİLMEDİ."""

        if query and is_complex_coding_query(query):
            claude_code = self.router.manager.get("claude_code")
            if claude_code is not None and claude_code.is_available():
                return "claude_code"

        if not preferred_provider:
            return "ollama"

        candidate = self.router.manager.get(preferred_provider)
        if candidate is not None and candidate.is_available():
            return preferred_provider

        return "ollama"
