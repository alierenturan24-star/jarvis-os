from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Job:

    id: str

    title: str

    tasks: list = field(default_factory=list)

    status: str = "waiting"

    created_at: datetime = field(default_factory=datetime.now)

    finished_at = None