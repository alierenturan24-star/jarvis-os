from dataclasses import dataclass
from datetime import datetime


@dataclass
class Experience:

    name: str

    version: str

    success: bool

    score: int

    notes: str

    created_at: datetime = datetime.now()