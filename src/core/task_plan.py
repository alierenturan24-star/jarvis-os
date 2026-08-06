from __future__ import annotations

from typing import Callable, Iterable, Optional

from src.jobs.task import Task
from src.jobs.task_queue import TaskQueue
from src.jobs.task_status import TaskStatus


class TaskPlanError(Exception):
    """TaskPlan oluşturma/doğrulama sırasında oluşan hatalar."""


class TaskPlan:
    """Tek bir kullanıcı komutunu, aralarında bağımlılık olabilen sıralı
    görevlere böler.

    ``src.jobs`` Task Engine'inin (``Task``, ``TaskQueue``, ``TaskStatus``)
    üzerine inşa edilmiştir; depolama ve öncelik sıralaması doğrudan
    ``TaskQueue``'ya devredilir, ``TaskPlan`` yalnızca bağımlılık grafiğini
    ekler. Gerçek çalıştırma ``PlanExecutor``'a aittir — bu sınıf hiçbir
    görevi çalıştırmaz.
    """

    def __init__(self, goal: str = "") -> None:
        self.goal = goal
        self._queue = TaskQueue()
        self._by_id: dict[str, Task] = {}

    # --- Kurulum -----------------------------------------------------------

    def add_task(
        self,
        task: Task,
        depends_on: Iterable[Task | str] = (),
    ) -> Task:
        """Plana bir görev ekler.

        ``depends_on``, bu plana DAHA ÖNCE eklenmiş ``Task`` nesneleri
        veya bunların id'leri olmalıdır (henüz eklenmemiş/gelecekteki bir
        göreve bağımlılık kurulamaz — bu da "ileriye referans" tipi
        çevrimleri baştan imkânsız kılar).

        Reddedilen durumlar (``TaskPlanError``, görev plana HİÇ eklenmez):
          - Aynı görev (``task.id``) plana ikinci kez eklenmeye çalışılırsa.
          - Bilinmeyen/plana eklenmemiş bir göreve bağımlılık kurulmaya
            çalışılırsa.
          - Eklenen bağımlılıklar mevcut grafikle birlikte bir döngü
            oluşturuyorsa.
        """

        if task.id in self._by_id:
            raise TaskPlanError(
                f"Bu görev plana zaten eklenmiş: {task.id} ({task.title!r})"
            )

        resolved_deps: list[str] = []

        for dep in depends_on:
            dep_id = dep.id if isinstance(dep, Task) else dep

            if dep_id not in self._by_id:
                raise TaskPlanError(
                    f"Bağımlılık plana eklenmemiş bir göreve işaret ediyor: {dep_id}"
                )

            resolved_deps.append(dep_id)

        for dep_id in resolved_deps:
            if dep_id not in task.depends_on:
                task.depends_on.append(dep_id)

        # Döngü kontrolü: görevi geçici olarak grafiğe ekleyip tüm grafikte
        # döngü olup olmadığına bakılır; döngü varsa ekleme geri alınır.
        self._by_id[task.id] = task
        cycle = self._find_cycle()

        if cycle is not None:
            del self._by_id[task.id]
            for dep_id in resolved_deps:
                if dep_id in task.depends_on:
                    task.depends_on.remove(dep_id)
            raise TaskPlanError(
                "Bağımlılık döngüsü tespit edildi: " + self._describe_cycle(cycle)
            )

        self._queue.add(task)
        return task

    def validate(self) -> None:
        """Planın TÜM bağımlılık grafiğinde döngü olup olmadığını doğrular.

        ``add_task`` yalnızca kendi API'si üzerinden kurulan bağımlılıkları
        kontrol edebilir; bir görevin ``depends_on`` listesi doğrudan (API
        dışından) değiştirilirse bu, ``add_task``'in döngü kontrolünü
        atlar. Bu yüzden ``PlanExecutor.run()``, herhangi bir görevi
        çalıştırmaya BAŞLAMADAN ÖNCE tüm grafiği burada yeniden doğrular.
        """

        cycle = self._find_cycle()

        if cycle is not None:
            raise TaskPlanError(
                "Bağımlılık döngüsü tespit edildi: " + self._describe_cycle(cycle)
            )

    def _find_cycle(self) -> Optional[list[str]]:
        """Plandaki tüm görevler üzerinde (klasik beyaz/gri/siyah) DFS ile
        bir bağımlılık döngüsü arar. Bulunursa döngüyü oluşturan görev
        id'lerinin listesini, yoksa ``None`` döndürür."""

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {task_id: WHITE for task_id in self._by_id}

        def visit(task_id: str, path: list[str]) -> Optional[list[str]]:
            color[task_id] = GRAY
            path.append(task_id)

            task = self._by_id.get(task_id)

            if task is not None:
                for dep_id in task.depends_on:
                    if dep_id not in color:
                        continue  # Bilinmeyen id: add_task zaten engeller.

                    if color[dep_id] == GRAY:
                        start = path.index(dep_id)
                        return path[start:]

                    if color[dep_id] == WHITE:
                        found = visit(dep_id, path)
                        if found is not None:
                            return found

            path.pop()
            color[task_id] = BLACK
            return None

        for task_id in list(self._by_id):
            if color[task_id] == WHITE:
                found = visit(task_id, [])
                if found is not None:
                    return found

        return None

    def _describe_cycle(self, cycle: list[str]) -> str:
        titles = [
            self._by_id[task_id].title if task_id in self._by_id else task_id
            for task_id in cycle
        ]
        if not titles:
            return ""
        return " -> ".join(titles + [titles[0]])

    # --- Sorgulama -----------------------------------------------------------

    def get(self, task_id: str) -> Optional[Task]:
        return self._by_id.get(task_id)

    def all_tasks(self) -> list[Task]:
        return self._queue.all()

    def pending_tasks(self) -> list[Task]:
        return self._queue.pending()

    def is_ready(self, task: Task) -> bool:
        """Görevin tüm bağımlılıkları TAMAMLANDI mı (yani görev başlayabilir mi)."""

        return all(
            self._by_id[dep_id].status == TaskStatus.COMPLETED
            for dep_id in task.depends_on
            if dep_id in self._by_id
        )

    def next_ready(self) -> Optional[Task]:
        """Bağımlılıkları tamamlanmış, bekleyen bir sonraki görevi döndürür.

        Birden fazla aday varsa önceliğe (yüksek önce), eşitlikte ekleme
        sırasına göre seçim yapılır — ``TaskQueue.next_pending`` ile aynı
        kural.
        """

        candidates = [task for task in self._queue.pending() if self.is_ready(task)]

        if not candidates:
            return None

        order = {task.id: index for index, task in enumerate(self._queue.all())}
        candidates.sort(key=lambda task: (-task.priority, order[task.id]))
        return candidates[0]

    def has_failed(self) -> bool:
        return bool(self._queue.by_status(TaskStatus.FAILED))

    def is_finished(self) -> bool:
        """Artık ne bekleyen ne de çalışan görev kalmadı mı."""

        return not self._queue.pending() and not self._queue.by_status(TaskStatus.RUNNING)

    def cancel_remaining(self, reason: str = "") -> list[Task]:
        """Hâlâ bekleyen (PENDING) tüm görevleri iptal eder ve iptal
        edilenlerin listesini döndürür. Zaten çalışan/biten görevlere
        dokunmaz."""

        cancelled: list[Task] = []

        for task in self._queue.pending():
            if reason and not task.error:
                task.error = reason
            task.cancel()
            cancelled.append(task)

        return cancelled

    def _transitive_dependents(self, task_id: str) -> set[str]:
        """``task_id``'ye doğrudan veya dolaylı (zincirleme) olarak bağımlı
        olan tüm görevlerin id'lerini döndürür (``task_id``'nin kendisi
        hariç)."""

        reverse: dict[str, list[str]] = {}
        for tid, task in self._by_id.items():
            for dep_id in task.depends_on:
                reverse.setdefault(dep_id, []).append(tid)

        result: set[str] = set()
        stack = [task_id]

        while stack:
            current = stack.pop()
            for child_id in reverse.get(current, []):
                if child_id not in result:
                    result.add(child_id)
                    stack.append(child_id)

        return result

    def cancel_dependents(self, task_id: str, reason: str = "") -> list[Task]:
        """``task_id``'ye doğrudan/dolaylı olarak bağımlı olan, hâlâ
        bekleyen (PENDING) görevleri iptal eder. Bu göreve bağımlı
        OLMAYAN (bağımsız) görevlere dokunmaz — onlar çalışmaya devam
        edebilir."""

        dependent_ids = self._transitive_dependents(task_id)
        cancelled: list[Task] = []

        for task in self._queue.pending():
            if task.id in dependent_ids:
                if reason and not task.error:
                    task.error = reason
                task.cancel()
                cancelled.append(task)

        return cancelled

    def summary(self) -> dict[str, int]:
        return {status.value: len(self._queue.by_status(status)) for status in TaskStatus}

    # --- Tek komuttan plan üretme -------------------------------------------

    @classmethod
    def from_command(
        cls,
        command: str,
        handlers: Optional[dict[str, Callable[[Task], object]]] = None,
    ) -> "TaskPlan":
        """Tek bir kullanıcı komutunu, doğrusal bağımlılığı olan beş
        standart adıma böler: analiz -> üretim -> biçimlendirme ->
        kaydetme -> bildirim.

        ``handlers`` verilirse, adım anahtarına (``analyze``, ``build``,
        ``format``, ``save``, ``notify``) göre ilgili görevin
        ``handler``'ı olarak atanır; verilmezse görev handler'sız kalır
        (``JobManager.run_task`` bunu başarısız/handler-yok olarak
        raporlar — mevcut Task Engine davranışı değiştirilmez).
        """

        command = (command or "").strip()
        plan = cls(goal=command)
        handlers = handlers or {}

        steps = (
            (
                "analyze",
                "İsteği analiz et",
                f"Kullanıcının isteğini analiz et: {command!r}",
            ),
            (
                "build",
                "İçeriği oluştur",
                "Analiz sonucuna göre istenen içeriği/planı oluştur.",
            ),
            (
                "format",
                "Markdown formatına dönüştür",
                "Üretilen içeriği Markdown formatına dönüştür.",
            ),
            (
                "save",
                "Dosyaya kaydet",
                "Biçimlendirilmiş içeriği dosyaya kaydet.",
            ),
            (
                "notify",
                "Sonucu kullanıcıya bildir",
                "Tamamlanan sonucu kullanıcıya bildir.",
            ),
        )

        previous: Optional[Task] = None

        for key, title, description in steps:
            task = Task(
                title=title,
                action=key,
                target=command,
                metadata={"description": description, "step": key},
                handler=handlers.get(key),
            )
            plan.add_task(task, depends_on=(previous,) if previous is not None else ())
            previous = task

        return plan
