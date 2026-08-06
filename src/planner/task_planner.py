from dataclasses import dataclass


@dataclass
class Task:
    agent: str
    action: str
    target: str = ""
    priority: int = 1
    completed: bool = False

    @property
    def name(self) -> str:
        if self.target:
            return f"{self.action}: {self.target}"

        return self.action


class TaskPlanner:

    def __init__(self):
        self.tasks: list[Task] = []

    def add_task(
        self,
        agent: str,
        action: str,
        target: str = "",
        priority: int = 1,
    ) -> Task:

        task = Task(
            agent=agent,
            action=action,
            target=target,
            priority=priority,
        )

        self.tasks.append(task)

        return task

    def get_tasks(self) -> list[Task]:
        return sorted(
            self.tasks,
            key=lambda task: task.priority,
            reverse=True,
        )

    def complete(self, task_name: str) -> bool:
        for task in self.tasks:
            if task.name == task_name:
                task.completed = True
                return True

        return False