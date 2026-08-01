class StateManager:

    IDLE = "idle"
    THINKING = "thinking"
    WORKING = "working"
    SLEEP = "sleep"

    def __init__(self):

        self.state = self.IDLE

    def set(self, state):

        self.state = state

    def get(self):

        return self.state