from src.core.task import Task


class TaskManager:

    def __init__(self):

        self.tasks = []

    def create_task(self, title, description):

        task = Task(
            title=title,
            description=description,
        )

        self.tasks.append(task)

        return task

    def get_tasks(self):

        return self.tasks

    def pending_tasks(self):

        return [
            t
            for t in self.tasks
            if t.status != "completed"
        ]