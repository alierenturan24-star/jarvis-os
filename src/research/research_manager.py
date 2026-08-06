from src.research.collector import ResearchCollector
from src.research.report_builder import ReportBuilder
from src.research.summarizer import Summarizer


class ResearchManager:

    def __init__(self) -> None:

        self.collector = ResearchCollector()
        self.summarizer = Summarizer()
        self.report_builder = ReportBuilder()

    def research(self, topic: str) -> str:

        topic = topic.strip()

        if not topic:
            return "Araştırılacak konu belirtilmedi."

        print(f"[Research] {topic} araştırılıyor...")

        results = self.collector.collect(
            topic=topic,
            max_results_per_source=3,
        )

        if not results:
            return (
                "Araştırma sonucu bulunamadı. "
                "İnternet bağlantısını kontrol et."
            )

        summary = self.summarizer.summarize(
            topic=topic,
            results=results,
        )

        report_path = self.report_builder.save(
            topic=topic,
            summary=summary,
            results=results,
        )

        return (
            f"Araştırma tamamlandı.\n\n"
            f"{summary}\n\n"
            f"Toplanan kaynak sayısı: {len(results)}\n"
            f"Rapor kaydedildi:\n{report_path}"
        )