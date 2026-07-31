from src.ai.brain import Brain
from src.core.commander import Commander


class Jarvis:
    def __init__(self):
        self.brain = Brain()
        self.commander = Commander()

    def chat(self, message: str) -> str:
        return self.commander.process(message)

    def remember(self, key, value):
        self.brain.remember(key, value)

    def recall(self, key):
        return self.brain.recall(key)