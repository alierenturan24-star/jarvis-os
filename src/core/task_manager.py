from copy import deepcopy


class TaskManager:
    """
    Planner tarafından oluşturulan görevleri yönetir.
    """

    def __init__(self):
        self.tasks = []

    def load(self, tasks):
        self.tasks = deepcopy(tasks)

    def get_all(self):
        return self.tasks

    def get_pending(self):
        return [
            task
            for task in self.tasks
            if task["status"] == "pending"
        ]

    def get_completed(self):
        return [
            task
            for task in self.tasks
            if task["status"] == "completed"
        ]

    def get_failed(self):
        return [
            task
            for task in self.tasks
            if task["status"] == "failed"
        ]

    def is_finished(self):

        for task in self.tasks:
            if task["status"] == "pending":
                return False

        return True

    def can_execute(self, task):

        for dep in task["depends_on"]:

            found = False

            for t in self.tasks:

                if t["id"] == dep:

                    if t["status"] == "completed":
                        found = True

            if not found:
                return False

        return True

    def next_task(self):

        for task in self.tasks:

            if (
                task["status"] == "pending"
                and
                self.can_execute(task)
            ):
                return task

        return None

    def complete(self, task_id, result=None):

        for task in self.tasks:

            if task["id"] == task_id:

                task["status"] = "completed"
                task["result"] = result
                return

    def fail(self, task_id, error=""):

        for task in self.tasks:

            if task["id"] == task_id:

                task["status"] = "failed"
                task["error"] = error
                return

    def reset(self):

        for task in self.tasks:

            task["status"] = "pending"
            task["result"] = None
            task["error"] = None