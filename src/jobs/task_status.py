from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    """Bir görevin yaşam döngüsü boyunca alabileceği durumlar."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
