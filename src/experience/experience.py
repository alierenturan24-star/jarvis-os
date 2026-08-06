from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Experience:
    name: str
    version: str
    success: bool
    score: int
    notes: str
    created_at: datetime = field(default_factory=datetime.now)
