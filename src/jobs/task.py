from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus


@dataclass
class Task:
    """Standartlaştırılmış görev birimi.

    Bu, JARVIS'in Task Engine'i için ortak görev modelidir; ileride
    Browser/Finance/YouTube gibi ajanların da üzerine inşa edebileceği
    tek, tutarlı bir sözleşme sağlamak amacıyla tasarlanmıştır.
    ``handler`` verilirse (``Callable[[Task], Any]``) görev JobManager
    tarafından retry/timeout/öncelik desteğiyle doğrudan çalıştırılabilir;
    verilmezse görev yalnızca veri taşıyıcı olarak kullanılabilir.
    """

    title: str
    agent: str = ""
    action: str = ""
    target: str = ""
    priority: int = 0
    max_retries: int = 0
    timeout_seconds: Optional[float] = None
    handler: Optional[Callable[["Task"], Any]] = None
    metadata: dict = field(default_factory=dict)

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    result: Optional[TaskResult] = None
    error: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    # Bu görevin başlayabilmesi için TAMAMLANMIŞ olması gereken diğer
    # görevlerin id'leri. Boş liste = bağımlılık yok. Bağımlılık grafiğinin
    # yorumlanması/yürütülmesi ``src.core.task_plan.TaskPlan`` ve
    # ``src.core.plan_executor.PlanExecutor``'a aittir; ``Task`` yalnızca
    # veriyi taşır.
    depends_on: list[str] = field(default_factory=list)

    def apply_result(self, result: TaskResult) -> None:
        """Bir çalıştırma sonucunu göreve işler ve durumunu günceller."""

        self.result = result
        self.attempts = result.attempts
        self.started_at = result.started_at or self.started_at
        self.finished_at = result.finished_at
        self.error = result.error
        self.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED

    def cancel(self) -> None:
        """Görevi iptal eder.

        Not: Yalnızca henüz çalışmaya başlamamış (PENDING) görevleri
        kuyruktan etkin şekilde düşürür; zaten RUNNING olan bir görevi
        yarıda kesmez (Python'da rastgele bir çağrılabiliri güvenle
        zorla durdurmanın standart bir yolu yoktur).
        """

        self.status = TaskStatus.CANCELLED
