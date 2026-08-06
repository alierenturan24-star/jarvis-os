from datetime import datetime


class Audit:

    def __init__(self):

        self.logs = []

    def log(self, action, detail=""):

        self.logs.append({

            "time": datetime.now(),

            "action": action,

            "detail": detail,

        })

    def latest(self):

        if not self.logs:
            return None

        return self.logs[-1]

    def all(self):

        return self.logs