from datetime import datetime


class Executor:

    def __init__(
        self,
        queue,
        router,
    ):

        self.queue = queue

        self.router = router

    def run(self):

        results = []

        while not self.queue.empty():

            task = self.queue.next()

            task.status = "running"

            result = self.router.execute(task)

            task.status = "finished"

            task.result = str(result)

            task.finished_at = datetime.now()

            results.append(result)

        return results