from src.jobs.job import Job


class JobManager:

    def __init__(self):

        self.jobs = {}

    def add(self, job: Job):

        self.jobs[job.id] = job

    def get(self, job_id):

        return self.jobs.get(job_id)

    def all(self):

        return list(self.jobs.values())

    def running(self):

        return [
            job
            for job in self.jobs.values()
            if job.status == "running"
        ]

    def completed(self):

        return [
            job
            for job in self.jobs.values()
            if job.status == "completed"
        ]