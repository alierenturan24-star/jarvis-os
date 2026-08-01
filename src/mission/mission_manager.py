from src.mission.mission import Mission


class MissionManager:

    def __init__(self):

        self.active = []

    def create(self, title, objective):

        mission = Mission(

            title=title,

            objective=objective,

        )

        self.active.append(mission)

        return mission

    def all(self):

        return self.active

    def complete(self, mission):

        mission.status = "DONE"