from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.jobs.task import Task
from src.jobs.task_queue import TaskQueue
from src.jobs.task_status import TaskStatus


@dataclass
class Job:
    """Bir veya daha fazla Task'i gruplayan iş birimi."""

    title: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    queue: TaskQueue = field(default_factory=TaskQueue)
    status: str = "waiting"
    created_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None

    @property
    def tasks(self) -> list[Task]:
        return self.queue.all()

    def add_task(self, task: Task) -> Task:
        return self.queue.add(task)

    def refresh_status(self) -> None:
        """Görev durumlarına bakarak job'un genel durumunu günceller."""

        tasks = self.queue.all()

        if not tasks:
            self.status = "waiting"
            return

        statuses = {task.status for task in tasks}

        if statuses <= {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
            self.status = "completed"
            self.finished_at = self.finished_at or datetime.now()
        elif TaskStatus.RUNNING in statuses:
            self.status = "running"
        elif TaskStatus.PENDING in statuses:
            self.status = "waiting"
        else:
            self.status = "failed"
            self.finished_at = self.finished_at or datetime.now()
