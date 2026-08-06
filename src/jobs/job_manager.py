from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import datetime
from typing import Optional

from src.jobs.jobs.job import Job
from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus


class JobManager:
    """Job/Task tabanlı gerçek bir görev kuyruğu ve çalıştırma motoru.

    Herhangi bir ajana bağımlı değildir: ``Task.handler`` üzerinden
    verilen herhangi bir çağrılabiliri (ileride Browser/Finance/YouTube
    ajanları dahil) öncelik sırası, retry ve timeout desteğiyle çalıştırır.
    Bu sınıf o ajanları içermez; onlar için ortak altyapı sağlar.
    """

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    # --- Job kayıt/erişim -------------------------------------------------

    def add(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job

    def create_job(self, title: str) -> Job:
        return self.add(Job(title=title))

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def all(self) -> list[Job]:
        return list(self.jobs.values())

    def running(self) -> list[Job]:
        return [job for job in self.jobs.values() if job.status == "running"]

    def completed(self) -> list[Job]:
        return [job for job in self.jobs.values() if job.status == "completed"]

    # --- Görev kuyruğu ------------------------------------------------------

    def submit_task(self, job_id: str, task: Task) -> bool:
        """Var olan bir job'a görev ekler."""

        job = self.get(job_id)

        if job is None:
            return False

        job.add_task(task)
        return True

    # --- Çalıştırma motoru ---------------------------------------------------

    def run_task(self, task: Task) -> TaskResult:
        """Tek bir görevi öncelik sırasından bağımsız, doğrudan çalıştırır.

        - Retry: ``task.max_retries`` kadar yeniden dener.
        - Timeout: ``task.timeout_seconds`` verildiyse süre aşımında
          görev başarısız sayılır (arka plandaki iş parçacığı Python'ın
          doğası gereği zorla durdurulamaz; bu bilinen bir kısıtlamadır).
        """

        if task.status == TaskStatus.CANCELLED:
            return task.result or TaskResult(success=False, error="Görev iptal edildi.")

        if task.handler is None:
            result = TaskResult(
                success=False,
                error="Görev için handler tanımlı değil.",
                attempts=task.attempts,
            )
            task.apply_result(result)
            return result

        max_attempts = max(task.max_retries, 0) + 1
        started_at = task.started_at or datetime.now()
        last_error = "Bilinmeyen hata."

        for attempt in range(1, max_attempts + 1):
            task.status = TaskStatus.RUNNING
            task.started_at = started_at
            # Handler calisirken guncel deneme numarasini gorebilsin diye
            # (retry gorunurlugu) attempts, sonucu beklemeden burada yazilir;
            # basarili/basarisiz nihai sonuc yine apply_result() ile yazilir.
            task.attempts = attempt

            executor = ThreadPoolExecutor(max_workers=1)

            try:
                future = executor.submit(task.handler, task)
                output = future.result(timeout=task.timeout_seconds)

                result = TaskResult(
                    success=True,
                    output=output,
                    attempts=attempt,
                    started_at=started_at,
                    finished_at=datetime.now(),
                )
                task.apply_result(result)
                return result

            except FuturesTimeoutError:
                last_error = f"Görev zaman aşımına uğradı ({task.timeout_seconds} sn)."

            except Exception as error:
                last_error = str(error)

            finally:
                # wait=False: zaman aşımına uğramış bir çağrının çağıranı
                # bloklamasını önler; arka plan iş parçacığı kendi başına
                # bitene kadar çalışmaya devam eder (Python'da zorla
                # durdurma yoktur).
                executor.shutdown(wait=False)

        result = TaskResult(
            success=False,
            error=last_error,
            attempts=max_attempts,
            started_at=started_at,
            finished_at=datetime.now(),
        )
        task.apply_result(result)
        return result

    def run_job(self, job_id: str) -> Optional[Job]:
        """Job'a ait tüm bekleyen görevleri öncelik sırasına göre çalıştırır."""

        job = self.get(job_id)

        if job is None:
            return None

        job.status = "running"

        while True:
            task = job.queue.next_pending()

            if task is None:
                break

            self.run_task(task)

        job.refresh_status()
        return job

    def run_pending(self) -> list[Job]:
        """Bekleyen görevi olan tüm job'ları çalıştırır."""

        return [
            self.run_job(job.id)
            for job in list(self.jobs.values())
            if job.queue.pending()
        ]
