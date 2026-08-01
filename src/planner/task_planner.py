from dataclasses import dataclass


@dataclass
class Task:
    name: str
    priority: int
    completed: bool = False


class TaskPlanner:

    def __init__(self):
        self.tasks = []

    def add_task(self, name, priority=1):
        self.tasks.append(
            Task(
                name=name,
                priority=priority,
            )
        )

    def get_tasks(self):
        return sorted(
            self.tasks,
            key=lambda t: t.priority,
            reverse=True,
        )

    def complete(self, name):
        for task in self.tasks:
            if task.name == name:
                task.completed = True