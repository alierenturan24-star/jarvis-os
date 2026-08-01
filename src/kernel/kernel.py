from datetime import datetime


class Kernel:

    def __init__(self):

        self.state = "BOOT"

        self.boot_time = datetime.now()

        self.active_jobs = []

        self.active_agents = []

        self.loaded_capabilities = []

    def boot(self):

        self.state = "READY"

    def sleep(self):

        self.state = "SLEEP"

    def wake(self):

        self.state = "READY"

    def shutdown(self):

        self.state = "OFF"

    def register_agent(self, name):

        if name not in self.active_agents:

            self.active_agents.append(name)

    def register_capability(self, name):

        if name not in self.loaded_capabilities:

            self.loaded_capabilities.append(name)

    def add_job(self, job):

        self.active_jobs.append(job)

    def finish_job(self, job):

        if job in self.active_jobs:

            self.active_jobs.remove(job)

    def status(self):

        return {

            "state": self.state,

            "boot_time": self.boot_time,

            "agents": self.active_agents,

            "jobs": len(self.active_jobs),

            "capabilities": len(self.loaded_capabilities),

        }