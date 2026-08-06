from src.planner.task import Task


class TaskQueue:

    def __init__(self) -> None:
        self.tasks: list[Task] = []

    def add(self, task: Task) -> None:
        self.tasks.append(task)
        self.tasks.sort(
            key=lambda item: item.priority,
            reverse=True,
        )

    def pop(self) -> Task | None:
        if not self.tasks:
            return None

        return self.tasks.pop(0)

    def next(self) -> Task | None:
        """
        Yeni Executor uyumluluğu.
        """
        return self.pop()

    def empty(self) -> bool:
        return len(self.tasks) == 0

    def clear(self) -> None:
        self.tasks.clear()

    def all(self) -> list[Task]:
        return list(self.tasks)

    def size(self) -> int:
        return len(self.tasks)