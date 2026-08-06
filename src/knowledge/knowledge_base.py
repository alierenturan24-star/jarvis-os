import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class KnowledgeBase:

    def __init__(self) -> None:

        self.folder = Path("workspace") / "knowledge"

        self.folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.file = self.folder / "knowledge.json"

        if not self.file.exists():
            self._save(
                {
                    "research": [],
                    "notes": {},
                }
            )

    def _load(self) -> dict[str, Any]:

        try:
            data = json.loads(
                self.file.read_text(
                    encoding="utf-8",
                )
            )

            if not isinstance(data, dict):
                raise ValueError("Bilgi tabanı biçimi geçersiz.")

            data.setdefault("research", [])
            data.setdefault("notes", {})

            return data

        except Exception:

            return {
                "research": [],
                "notes": {},
            }

    def _save(self, data: dict[str, Any]) -> None:

        self.file.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=4,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def normalize(text: str) -> str:

        text = text.casefold().strip()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text)

        return text.strip()

    def remember_research(
        self,
        topic: str,
        summary: str,
        report_path: str,
        source_count: int,
    ) -> None:

        data = self._load()

        normalized_topic = self.normalize(topic)

        record = {
            "topic": topic,
            "normalized_topic": normalized_topic,
            "summary": summary,
            "report_path": report_path,
            "source_count": source_count,
            "created_at": datetime.now().isoformat(
                timespec="seconds"
            ),
        }

        existing_index = None

        for index, item in enumerate(data["research"]):

            if item.get("normalized_topic") == normalized_topic:
                existing_index = index
                break

        if existing_index is None:
            data["research"].append(record)
        else:
            data["research"][existing_index] = record

        self._save(data)

    def find_research(
        self,
        topic: str,
    ) -> dict[str, Any] | None:

        normalized_topic = self.normalize(topic)

        for item in reversed(self._load()["research"]):

            stored_topic = item.get(
                "normalized_topic",
                "",
            )

            if (
                stored_topic == normalized_topic
                or normalized_topic in stored_topic
                or stored_topic in normalized_topic
            ):
                return item

        return None

    def recent_research(
        self,
        limit: int = 10,
    ) -> list[dict[str, Any]]:

        research = self._load()["research"]

        return list(
            reversed(research)
        )[:limit]

    def remember(
        self,
        key: str,
        value: Any,
    ) -> None:

        data = self._load()

        data["notes"][key] = value

        self._save(data)

    def recall(
        self,
        key: str,
    ) -> Any:

        return self._load()["notes"].get(key)

    def all(self) -> dict[str, Any]:

        return self._load()