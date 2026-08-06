from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class TaskResult:
    """Bir görevin çalıştırılma sonucunu taşıyan standart sonuç nesnesi."""

    success: bool
    output: Any = None
    error: str = ""
    attempts: int = 1
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()
