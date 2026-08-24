import json
import re
import hashlib
import uuid
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
            data.setdefault("facts", [])

            return data

        except Exception:

            return {
                "research": [],
                "notes": {},
                "facts": [],
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
        sources: list[dict[str, Any]] | None = None,
        provenance: str = "legacy_unverified",
        confidence: float | None = None,
    ) -> None:

        data = self._load()

        normalized_topic = self.normalize(topic)

        record = {
            "topic": topic,
            "normalized_topic": normalized_topic,
            "summary": summary,
            "report_path": report_path,
            "source_count": source_count,
            "sources": [
                {"source": str(item.get("source", "")), "title": str(item.get("title", "")),
                 "url": str(item.get("url", ""))}
                for item in (sources or []) if str(item.get("url", "")).strip()
            ],
            "provenance": provenance,
            "confidence": confidence,
            "created_at": datetime.now().astimezone().isoformat(
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

    # Sprint 38 canlı testinde yakalandı: saf alt-dize (substring) eşleşmesi,
    # KISA bir önbellek kaydının (ör. "güvenlik") çok UZUN, çok konulu yeni
    # bir istekte (ör. Autonomous Research Loop'un ham hedef cümlesini
    # AYNEN topic olarak geçtiği, "... güvenlik riskini ..." gibi tek bir
    # kelimeyi de İÇEREN uzun bir paragraf) alakasız şekilde EŞLEŞMESİNE yol
    # açıyordu -- eski, tamamen alakasız bir "güvenlik" araştırması geri
    # dönüyordu. Artık alt-dize eşleşmesi yalnızca KISA olan metin, UZUN
    # olanın en az bu ORANI kadar uzunluktaysa kabul edilir; tam eşleşme
    # (``stored_topic == normalized_topic``) her zaman geçerli kalır.
    _MIN_CONTAINMENT_RATIO = 0.4

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

            if stored_topic == normalized_topic:
                return item

            if not stored_topic or not normalized_topic:
                continue

            shorter, longer = sorted(
                (stored_topic, normalized_topic), key=len,
            )

            if shorter in longer and len(shorter) >= len(longer) * self._MIN_CONTAINMENT_RATIO:
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

    def facts(self, topic_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._load().get("facts", [])
        return [item for item in rows if topic_id is None or item.get("topic_id") == topic_id]

    @classmethod
    def fact_identity(cls, subject: str, predicate: str) -> str:
        raw = f"{cls.normalize(subject)}|{cls.normalize(predicate)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def persist_fact(self, finding: dict[str, Any], decision: str) -> dict[str, Any] | None:
        """Persist a gated external fact while preserving supersession/conflict history."""
        if decision not in {"ACCEPT_NEW", "UPDATE_EXISTING", "CONFLICT"}:
            return None
        provenance = finding.get("provenance") or {}
        # Defense in depth: callers cannot turn unverified external search text
        # into durable ACTIVE knowledge merely by supplying an accept decision.
        if (not provenance.get("durable_eligible") or provenance.get("source_quality_rejected")
                or provenance.get("verification_state") == "UNVERIFIED"):
            return None
        data = self._load()
        facts = data.setdefault("facts", [])
        identity = self.fact_identity(str(finding["subject"]), str(finding["predicate"]))
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        record = {
            "id": uuid.uuid4().hex, "topic_id": finding.get("topic_id"),
            "subject": finding["subject"], "predicate": finding["predicate"], "value": finding["value"],
            "normalized_value": self.normalize(str(finding["value"])), "fact_identity": identity,
            "status": "CONFLICT" if decision == "CONFLICT" else "ACTIVE", "superseded_by": None,
            "provenance": dict(finding["provenance"]), "confidence": float(finding.get("confidence", 0)),
            "created_at": now, "updated_at": now,
        }
        active = [row for row in facts if row.get("fact_identity") == identity and row.get("status") == "ACTIVE"]
        if decision == "UPDATE_EXISTING":
            for old in active:
                old.update(status="SUPERSEDED", superseded_by=record["id"], updated_at=now)
        elif decision == "CONFLICT":
            for old in active:
                old.update(status="CONFLICT", updated_at=now)
        facts.append(record)
        self._save(data)
        return record
