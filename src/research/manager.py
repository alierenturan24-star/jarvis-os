import re
import time
from datetime import datetime

from src.config.settings import Settings
from src.knowledge.knowledge_base import KnowledgeBase
from src.research.collector import MAX_SEARCH_STEPS, ResearchCollector
from src.research.report_builder import ReportBuilder
from src.research.summarizer import Summarizer
from src.utils.llm_utils import is_llm_failure

# Mission repair (real Swiss-Insider-Shorts follow-up evidence, item 5): a
# real mission asking for "today's"/"current" opportunity got back a
# summary titled "...2024'te En Çok Kazandıran..." while the system clock
# was 2026 -- with no mechanism anywhere flagging the mismatch. Generic
# (no hardcoded topic/year): a request that explicitly asks for current/
# today's information, whose result text only cites a year strictly
# OLDER than the system's current year, gets an explicit staleness
# warning attached -- never silently returned as if it were current.
# Does NOT reject/block (a genuinely historical year can be legitimately
# relevant, e.g. "compare this year to 2024") -- it makes the mismatch
# visible instead of hiding it, matching this codebase's "no fabricated
# success" pattern used elsewhere (CAPABILITY_GAP, VIDEO RENDER: BLOCKED).
_CURRENCY_CUES = (
    "today", "bugün", "current", "güncel", "now", "şu an", "şu anda",
    "this week", "bu hafta", "currently", "as of today", "right now",
)
_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")


def topic_wants_current_information(topic: str) -> bool:
    lowered = (topic or "").casefold()
    return any(cue in lowered for cue in _CURRENCY_CUES)


def staleness_warning(topic: str, text: str, *, current_year: int | None = None) -> str | None:
    """``None`` when nothing is stale (including: topic doesn't ask for
    current info, or no year is mentioned at all, or at least one
    mentioned year is current/future). Otherwise a truthful warning
    string citing the stale year(s) found and the real system year."""

    if not topic_wants_current_information(topic):
        return None
    years = {int(match) for match in _YEAR_PATTERN.findall(text or "")}
    if not years:
        return None
    year_now = current_year if current_year is not None else datetime.now().year
    if max(years) >= year_now:
        return None
    stale_years = ", ".join(str(year) for year in sorted(years))
    return (
        f"UYARI (GÜNCELLİK): İstek \"bugün/güncel\" bilgi istiyor ancak bulunan içerik yalnızca "
        f"geçmiş yıl(lar)a ({stale_years}) ait görünüyor -- sistem tarihi {year_now}. Bu özet GÜNCEL "
        "bir bulgu olarak GÜVENİLMEMELİDİR; konu daha güncel kaynaklarla yeniden araştırılmalı "
        "(force_refresh)."
    )


class ResearchManager:
    def __init__(self) -> None:
        self.collector = ResearchCollector()
        self.summarizer = Summarizer()
        self.report_builder = ReportBuilder()
        self.knowledge = KnowledgeBase()

    def research(
        self, topic: str, force_refresh: bool = False,
        preferred_provider: str | None = None, evidence_only: bool = False,
    ) -> str:
        topic = topic.strip()
        if not topic:
            return "Araştırılacak konu belirtilmedi."

        previous = self.knowledge.find_research(topic)
        previous_summary = str(previous.get("summary", "")) if previous else ""
        invalid_cache = previous is not None and is_llm_failure(previous_summary)

        if previous and not force_refresh and not invalid_cache:
            cache_staleness = staleness_warning(topic, previous_summary)
            return (
                "Bu konu daha önce araştırılmış.\n\n"
                f"Konu: {previous.get('topic', topic)}\n"
                f"Tarih: {previous.get('created_at', '')}\n"
                f"Kaynak sayısı: {previous.get('source_count', 0)}\n\n"
                f"Önceki özet:\n{previous_summary}\n\n"
                f"Rapor:\n{previous.get('report_path', '')}\n\n"
                "Yeniden araştırmak için komuta 'güncelle' kelimesini ekle."
                + (f"\n\n{cache_staleness}" if cache_staleness else "")
            )

        if evidence_only:
            return (
                f"Named target: {topic}. Exact GitHub/browser evidence stagesine devredildi; "
                "genel veya alakasız cache kanıt sayılmadı."
            )

        if invalid_cache:
            print("[Research] Önceki zaman aşımı kaydı geçersiz; araştırma yenileniyor...")
        print(f"[Research] {topic} araştırılıyor...")

        # Sprint: research/production pipeline audit -- self-bound the
        # sequential search-channel loop to a real budget (previously
        # unbounded here: collect()'s deadline param existed but was never
        # passed, so a slow early search could silently eat into what the
        # outer department timeout assumed was available for the
        # summarization call after it).
        deadline = time.monotonic() + Settings.RESEARCH_PROVIDER_TIMEOUT_SECONDS * MAX_SEARCH_STEPS
        try:
            results = self.collector.collect(topic=topic, max_results_per_source=3, deadline=deadline)
        except TimeoutError:
            return "Araştırma kaynak toplama süresi doldu (RESEARCH_CYCLE_MAX_RUNTIME_EXCEEDED)."
        if not results:
            return "Araştırma sonucu bulunamadı. İnternet bağlantısını kontrol et."

        summary = self.summarizer.summarize(
            topic=topic, results=results, preferred_provider=preferred_provider,
        )
        if is_llm_failure(summary):
            return "Araştırma kaynakları toplandı ancak güvenilir bir sentez üretilemedi; bilgi kalıcı hafızaya yazılmadı."
        report_path = self.report_builder.save(topic=topic, summary=summary, results=results)
        remember = dict(topic=topic, summary=summary, report_path=str(report_path), source_count=len(results))
        try:
            self.knowledge.remember_research(
                **remember, sources=results, provenance="external_research",
                confidence=min(1.0, len({item.get("url") for item in results if item.get("url")}) / 3.0),
            )
        except TypeError as error:
            if "unexpected keyword argument" not in str(error):
                raise
            self.knowledge.remember_research(**remember)

        fresh_staleness = staleness_warning(topic, summary)
        return (
            "Araştırma tamamlandı.\n\n"
            f"{summary}\n\n"
            f"Toplanan kaynak sayısı: {len(results)}\n"
            f"Rapor kaydedildi:\n{report_path}"
            + (f"\n\n{fresh_staleness}" if fresh_staleness else "")
        )
