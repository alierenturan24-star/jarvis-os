class Executor:

    def __init__(self, queue, agent_router):

        self.queue = queue

        self.agent_router = agent_router

    def run(self):

        results = []

        while not self.queue.empty():

            task = self.queue.pop()

            result = self.agent_router.execute(task)

            task.status = "completed"

            results.append(result)

        return results