from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class AgentResult:
    """Bir ajan çalıştırmasının standart, yapılandırılmış sonucu.

    ``BaseAgent.run()`` tarafından üretilir; Task Engine (``src/jobs``)
    ile uyumluluk ve gelecekteki ortak raporlama için kullanılır.
    """

    agent: str
    success: bool
    output: Optional[str] = None
    error: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def __str__(self) -> str:
        if self.success and self.output is not None:
            return self.output
        return self.error or "Ajan sonuç üretmedi."
