class TaskQueue:

    def __init__(self):

        self.tasks = []

    def add(self, task):

        self.tasks.append(task)

    def pop(self):

        if self.tasks:
            return self.tasks.pop(0)

        return None

    def empty(self):

        return len(self.tasks) == 0

    def clear(self):

        self.tasks.clear()

    def all(self):

        return self.tasks