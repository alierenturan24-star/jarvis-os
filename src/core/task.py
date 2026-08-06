from dataclasses import dataclass, field
from datetime import datetime
import uuid


@dataclass
class Task:

    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    agent: str = "chat"

    action: str = ""

    target: str = ""

    priority: int = 1

    status: str = "waiting"

    result: str = ""

    error: str = ""

    created_at: datetime = field(default_factory=datetime.now)

    finished_at: datetime | None = None

    metadata: dict = field(default_factory=dict)