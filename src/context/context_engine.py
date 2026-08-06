import json
from pathlib import Path
from typing import Any

from src.context.document_loader import DocumentLoader


class ContextEngine:
    """JARVIS kimliğini, proje durumunu ve kısa hafıza özetini birleştirir."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.loader = DocumentLoader(self.root)

    def _recent_knowledge(self, limit: int = 5) -> str:
        path = self.root / "workspace" / "knowledge" / "knowledge.json"

        try:
            if not path.is_file():
                return "Kayıtlı araştırma bulunmuyor."

            data: dict[str, Any] = json.loads(
                path.read_text(encoding="utf-8")
            )
            records = data.get("research", [])

            if not isinstance(records, list) or not records:
                return "Kayıtlı araştırma bulunmuyor."

            lines = []
            for record in records[-limit:]:
                if not isinstance(record, dict):
                    continue
                topic = str(record.get("topic", "")).strip()
                created_at = str(record.get("created_at", "")).strip()
                source_count = record.get("source_count", 0)
                if topic:
                    lines.append(
                        f"- {topic} | tarih: {created_at or 'bilinmiyor'} | "
                        f"kaynak: {source_count}"
                    )

            return "\n".join(lines) or "Kayıtlı araştırma bulunmuyor."
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
            return "Bilgi tabanı şu anda okunamadı."

    def build(self, task: str, include_memory: bool = True) -> str:
        constitution = self.loader.read("docs/constitution.md")
        mission = self.loader.read("docs/mission.md")
        project = self.loader.read("docs/project_context.md")
        memory = self._recent_knowledge() if include_memory else "Ek hafıza eklenmedi."

        return f"""## JARVIS KİMLİĞİ VE KURALLARI
{constitution}

## MİSYON
{mission}

## PROJE DURUMU
{project}

## YAKIN BİLGİ TABANI KAYITLARI
{memory}

## GÜNCEL GÖREV
{task.strip()}
""".strip()
