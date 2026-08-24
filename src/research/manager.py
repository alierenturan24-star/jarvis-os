import time

from src.config.settings import Settings
from src.knowledge.knowledge_base import KnowledgeBase
from src.research.collector import MAX_SEARCH_STEPS, ResearchCollector
from src.research.report_builder import ReportBuilder
from src.research.summarizer import Summarizer
from src.utils.llm_utils import is_llm_failure


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
            return (
                "Bu konu daha önce araştırılmış.\n\n"
                f"Konu: {previous.get('topic', topic)}\n"
                f"Tarih: {previous.get('created_at', '')}\n"
                f"Kaynak sayısı: {previous.get('source_count', 0)}\n\n"
                f"Önceki özet:\n{previous_summary}\n\n"
                f"Rapor:\n{previous.get('report_path', '')}\n\n"
                "Yeniden araştırmak için komuta 'güncelle' kelimesini ekle."
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

        return (
            "Araştırma tamamlandı.\n\n"
            f"{summary}\n\n"
            f"Toplanan kaynak sayısı: {len(results)}\n"
            f"Rapor kaydedildi:\n{report_path}"
        )
