from datetime import datetime
from pathlib import Path
import re


class ReportBuilder:

    def __init__(self) -> None:

        self.folder = Path("workspace") / "research"

        self.folder.mkdir(
            parents=True,
            exist_ok=True,
        )

    # Windows MAX_PATH (260 karakter) sınırını aşan uzun konu başlıkları
    # (ör. tüm cümleyi konu olarak geçen uzun istekler) "[Errno 22] Invalid
    # argument" ile dosya yazımını ÇÖKERTİYORDU (Sprint 37 canlı testinde
    # yakalandı) -- dosya adı burada güvenli bir uzunlukta kesiliyor,
    # içerik/summary KISALTILMIYOR.
    _MAX_FILENAME_TOPIC_LENGTH = 80

    @staticmethod
    def _safe_filename(topic: str) -> str:

        filename = topic.casefold().strip()
        filename = re.sub(r"[^\w\s-]", "", filename)
        filename = re.sub(r"[\s-]+", "_", filename)
        filename = filename[:ReportBuilder._MAX_FILENAME_TOPIC_LENGTH].rstrip("_")

        return filename or "arastirma"

    def save(
        self,
        topic: str,
        summary: str,
        results: list[dict],
    ) -> Path:

        timestamp = datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )

        filename = (
            f"{self._safe_filename(topic)}_"
            f"{timestamp}.md"
        )

        path = self.folder / filename

        source_blocks = []

        for index, result in enumerate(results, start=1):

            source_blocks.append(
                f"""
### {index}. {result.get("title", "Başlıksız kaynak")}

- Platform: {result.get("source", "Web")}
- Adres: {result.get("url", "")}
- Açıklama: {result.get("summary", "")}
""".strip()
            )

        sources_text = "\n\n".join(source_blocks)

        content = f"""# {topic}

## Araştırma Tarihi

{datetime.now().strftime("%d.%m.%Y %H:%M")}

## JARVIS Araştırma Özeti

{summary}

## Kullanılan Kaynaklar

{sources_text}
"""

        path.write_text(
            content,
            encoding="utf-8",
        )

        return path