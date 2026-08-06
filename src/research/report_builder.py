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

    @staticmethod
    def _safe_filename(topic: str) -> str:

        filename = topic.casefold().strip()
        filename = re.sub(r"[^\w\s-]", "", filename)
        filename = re.sub(r"[\s-]+", "_", filename)

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