from collections import deque


class Scheduler:

    def __init__(self):

        self.queue = deque()

    def add(self, task):

        self.queue.append(task)

    def next(self):

        if self.queue:

            return self.queue.popleft()

        return None

    def has_tasks(self):

        return len(self.queue) > 0

    def clear(self):

        self.queue.clear()

    def count(self):

        return len(self.queue)