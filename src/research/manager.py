from src.knowledge.knowledge_base import KnowledgeBase
from src.research.collector import ResearchCollector
from src.research.report_builder import ReportBuilder
from src.research.summarizer import Summarizer
from src.utils.llm_utils import is_llm_failure


class ResearchManager:
    def __init__(self) -> None:
        self.collector = ResearchCollector()
        self.summarizer = Summarizer()
        self.report_builder = ReportBuilder()
        self.knowledge = KnowledgeBase()

    def research(self, topic: str, force_refresh: bool = False) -> str:
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

        if invalid_cache:
            print("[Research] Önceki zaman aşımı kaydı geçersiz; araştırma yenileniyor...")
        print(f"[Research] {topic} araştırılıyor...")

        results = self.collector.collect(topic=topic, max_results_per_source=3)
        if not results:
            return "Araştırma sonucu bulunamadı. İnternet bağlantısını kontrol et."

        summary = self.summarizer.summarize(topic=topic, results=results)
        report_path = self.report_builder.save(topic=topic, summary=summary, results=results)
        self.knowledge.remember_research(
            topic=topic,
            summary=summary,
            report_path=str(report_path),
            source_count=len(results),
        )

        return (
            "Araştırma tamamlandı.\n\n"
            f"{summary}\n\n"
            f"Toplanan kaynak sayısı: {len(results)}\n"
            f"Rapor kaydedildi:\n{report_path}"
        )
