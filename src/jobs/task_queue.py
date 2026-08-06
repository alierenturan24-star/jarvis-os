from __future__ import annotations

import itertools
from typing import Optional

from src.jobs.task import Task
from src.jobs.task_status import TaskStatus


class TaskQueue:
    """Önceliğe göre sıralanan görev kuyruğu.

    Yüksek ``priority`` değeri önce çalışır; eşit öncelikte ekleme
    sırası (FIFO) korunur. Görevler çalıştırıldıktan sonra da geçmiş
    olarak kuyrukta kalır (fiziksel olarak çıkarılmaz); ``next_pending``
    yalnızca bir sonraki çalıştırılabilir görevi seçer.
    """

    def __init__(self) -> None:
        self._tasks: list[Task] = []
        self._order: dict[str, int] = {}
        self._counter = itertools.count()

    def __len__(self) -> int:
        return len(self._tasks)

    def add(self, task: Task) -> Task:
        self._tasks.append(task)
        self._order[task.id] = next(self._counter)
        return task

    def is_empty(self) -> bool:
        return not self._tasks

    def all(self) -> list[Task]:
        return list(self._tasks)

    def by_status(self, status: TaskStatus) -> list[Task]:
        return [task for task in self._tasks if task.status == status]

    def pending(self) -> list[Task]:
        return self.by_status(TaskStatus.PENDING)

    def next_pending(self) -> Optional[Task]:
        """Önceliği en yüksek (eşitlikte önce eklenen) PENDING görevi döndürür."""

        candidates = self.pending()

        if not candidates:
            return None

        candidates.sort(key=lambda task: (-task.priority, self._order[task.id]))
        return candidates[0]

    def remove(self, task_id: str) -> bool:
        for index, task in enumerate(self._tasks):
            if task.id == task_id:
                del self._tasks[index]
                self._order.pop(task_id, None)
                return True
        return False

    def clear(self) -> None:
        self._tasks.clear()
        self._order.clear()
