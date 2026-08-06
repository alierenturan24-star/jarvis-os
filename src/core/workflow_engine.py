from src.core.executor import Executor
from src.core.result_aggregator import ResultAggregator
from src.planner.planner import Planner
from src.planner.task import Task
from src.planner.task_queue import TaskQueue


class WorkflowEngine:
    """Planlama, kuyruk, yürütme ve sonuç birleştirmeyi tek yerde yönetir."""

    def __init__(self, router) -> None:
        self.planner = Planner()
        self.queue = TaskQueue()
        self.executor = Executor(self.queue, router)
        self.aggregator = ResultAggregator()

    def run(self, message: str) -> str:
        tasks = self.planner.build(message)

        if not tasks:
            return "Çalıştırılacak görev oluşturulamadı."

        self.queue.clear()
        for task in tasks:
            self.queue.add(task)

        ordered_tasks: list[Task] = self.queue.all()
        results = self.executor.run()

        return self.aggregator.aggregate(
            tasks=ordered_tasks,
            results=results,
        )
