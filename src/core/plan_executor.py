from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.core.task_plan import TaskPlan
from src.jobs.job_manager import JobManager
from src.jobs.task import Task
from src.jobs.task_status import TaskStatus


@dataclass
class PlanExecutionReport:
    """Bir ``TaskPlan`` çalıştırmasının sonucu."""

    plan: TaskPlan
    executed: list[Task] = field(default_factory=list)
    cancelled: list[Task] = field(default_factory=list)
    success: bool = False

    def describe(self) -> str:
        lines = [f"Plan: {self.plan.goal or '(isimsiz)'}"]

        for task in self.executed:
            lines.append(
                f"  [{task.status.value}] {task.title} "
                f"(deneme: {task.attempts}, hata: {task.error or '-'})"
            )

        for task in self.cancelled:
            lines.append(f"  [{task.status.value}] {task.title} (iptal edildi)")

        lines.append(f"Sonuç: {'başarılı' if self.success else 'başarısız'}")
        lines.append(f"Özet: {self.plan.summary()}")

        return "\n".join(lines)


class PlanExecutor:
    """``TaskPlan`` içindeki görevleri bağımlılık sırasına göre çalıştırır.

    Kurallar:
      - Çalıştırmaya başlamadan ÖNCE ``TaskPlan.validate()`` ile plan
        grafiğinde döngü olup olmadığı doğrulanır; döngü varsa hiçbir
        görev çalıştırılmadan ``TaskPlanError`` fırlatılır.
      - Bir görev, TÜM bağımlılıkları tamamlanmadan başlamaz
        (``TaskPlan.next_ready``).
      - Yeniden deneme tamamen mevcut Task Engine'in
        (``JobManager.run_task`` / ``Task.max_retries``) sorumluluğundadır;
        burada ayrıca bir retry döngüsü UYGULANMAZ — davranış tekrarlanmaz,
        yalnızca kullanılır.
      - ``cancel_on_failure=True`` (varsayılan) ise bir görev tüm
        denemelerine rağmen başarısız olursa, YALNIZCA o göreve doğrudan
        veya dolaylı olarak bağımlı olan bekleyen görevler iptal edilir
        (``TaskPlan.cancel_dependents``); çalıştırma DURMAZ, ilişkisiz
        (bağımsız) dallar normal şekilde çalışmaya devam eder.
      - Döngü sonunda, bağımlılığı hiçbir zaman tamamlanamayacak (ör.
        ``cancel_on_failure=False`` iken başarısız bir göreve bağımlı
        kalmış) bekleyen görevler varsa, bunlar da iptal edilir — aksi
        hâlde sonsuza dek "bekliyor" durumunda kalırlardı.
    """

    def __init__(
        self,
        job_manager: Optional[JobManager] = None,
        *,
        cancel_on_failure: bool = True,
    ) -> None:
        self.job_manager = job_manager or JobManager()
        self.cancel_on_failure = cancel_on_failure

    def run(self, plan: TaskPlan) -> PlanExecutionReport:
        plan.validate()

        executed: list[Task] = []

        while True:
            task = plan.next_ready()

            if task is None:
                break

            print(f"[AŞAMA: {task.agent.upper()}]", flush=True)
            self.job_manager.run_task(task)
            executed.append(task)

            if task.status == TaskStatus.FAILED and self.cancel_on_failure:
                plan.cancel_dependents(
                    task.id,
                    reason=f'Bağımlı olduğu görev başarısız oldu: "{task.title}"',
                )
                # Not: burada DURMUYORUZ -- bağımsız dallar hazır olduğu
                # sürece döngü devam eder ve çalıştırılır.

        # Kalan bekleyen görevler varsa (ör. cancel_on_failure=False iken
        # başarısız bir göreve bağımlı kalmış, veya başka bir sebeple hiç
        # hazır hâle gelemeyen görevler), bunlar iptal edilir.
        deadlocked = plan.pending_tasks()
        if deadlocked:
            plan.cancel_remaining(reason="Bağımlılığı hiçbir zaman tamamlanamadı.")

        return PlanExecutionReport(
            plan=plan,
            executed=executed,
            cancelled=[t for t in plan.all_tasks() if t.status == TaskStatus.CANCELLED],
            success=not plan.has_failed(),
        )
