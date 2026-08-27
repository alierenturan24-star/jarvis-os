from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Sprint 40 (LEARNING FROM EXECUTION): her ``route_and_generate`` çağrısından
# sonra hangi provider/görev-türü için ne olduğunu (başarı/fallback/süre)
# kaydeder. ``src.knowledge.knowledge_base.KnowledgeBase`` (Sprint 8) ile
# AYNI düz-JSON dosya deseni -- İKİNCİ bir veritabanı/hafıza sistemi İCAT
# ETMEZ, yalnızca aynı deseni provider çağrıları için kullanır.
#
# KURAL: JARVIS burada kendi model ağırlıklarını EĞİTMEZ, kendi production
# kodunu OTOMATİK DEĞİŞTİRMEZ -- bu yalnızca "hangi provider hangi görev
# türünde daha iyi çalıştı?" sorusuna gelecekteki bir OKUMA için veri
# biriktirir (bkz. ``success_rate``); hiçbir yazma işlemi bir routing
# kararını OTOMATİK değiştirmez.
MAX_ENTRIES = 500


class ProviderExecutionHistory:
    def __init__(self) -> None:
        self.folder = Path("workspace") / "knowledge"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.file = self.folder / "provider_execution_history.json"
        if not self.file.exists():
            self._save([])

    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save(self, entries: list[dict[str, Any]]) -> None:
        self.file.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    def record(
        self,
        *,
        task_type: str,
        provider: str,
        success: bool,
        fallback_used: bool,
        duration_seconds: float,
        queue_wait_seconds: Optional[float] = None,
        inference_seconds: Optional[float] = None,
        resource_type: Optional[str] = None,
        cost_class: Optional[str] = None,
    ) -> None:
        # Sprint 41 (QUEUE WAIT vs INFERENCE TIME): ``queue_wait_seconds``/
        # ``inference_seconds`` İSTEĞE BAĞLI -- yalnızca zamanlamayı
        # AYRIŞTIRABİLEN provider'lar (bkz. ``OllamaProvider.last_call_timing``)
        # doldurur. Eski kayıtlar bu alanları HİÇ İÇERMEZ -- ``recent()``/
        # ``success_rate()`` bunlara bağımlı DEĞİLDİR, geriye dönük
        # uyumluluk BOZULMAZ.
        entry: dict[str, Any] = {
            "task_type": task_type,
            "provider": provider,
            "success": success,
            "fallback_used": fallback_used,
            "duration_seconds": duration_seconds,
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
        }
        if queue_wait_seconds is not None:
            entry["queue_wait_seconds"] = queue_wait_seconds
        if inference_seconds is not None:
            entry["inference_seconds"] = inference_seconds
        if resource_type is not None:
            entry["resource_type"] = resource_type
        if cost_class is not None:
            # "free"/"plan"/"paid"/"unknown" -- bkz. CostOptimizer.cost_class.
            # Yalnızca doğrulanabilir sınıflandırma yazılır, uydurulmaz.
            entry["cost_class"] = cost_class

        entries = self._load()
        entries.append(entry)
        # Sınırsız büyümeyi önlemek için yalnızca son MAX_ENTRIES kayıt tutulur.
        entries = entries[-MAX_ENTRIES:]
        self._save(entries)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(reversed(self._load()))[:limit]

    def recent_for(self, provider: str, task_type: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]:
        """Most-recent-first entries for one provider (optionally narrowed
        to a task_type/capability) -- used by
        ``src.media.provider_selection.provider_health`` for bounded,
        auto-recovering cooldown detection. Same store, no second read
        path."""
        entries = [
            entry
            for entry in self._load()
            if entry.get("provider") == provider
            and (task_type is None or entry.get("task_type") == task_type)
        ]
        return list(reversed(entries))[:limit]

    def success_rate(self, provider: str, task_type: Optional[str] = None) -> Optional[float]:
        """``provider``'ın (isteğe bağlı ``task_type`` ile daraltılmış)
        geçmiş başarı oranı -- veri yoksa ``None`` (uydurma bir sayı
        DÖNMEZ)."""

        entries = [
            entry
            for entry in self._load()
            if entry.get("provider") == provider
            and (task_type is None or entry.get("task_type") == task_type)
        ]
        if not entries:
            return None

        successes = sum(1 for entry in entries if entry.get("success"))
        return round(100.0 * successes / len(entries), 1)
