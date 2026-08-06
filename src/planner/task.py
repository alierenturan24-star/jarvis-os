from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass
class Task:
    agent: str
    action: str
    target: str = ""
    priority: int = 1
    status: str = "waiting"
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    result: str = ""
    error: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None

    @property
    def name(self) -> str:
        return f"{self.action}: {self.target}" if self.target else self.action
