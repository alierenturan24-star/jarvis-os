from abc import ABC, abstractmethod


class BaseAgent(ABC):

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def execute(self, task: str) -> str:
        raise NotImplementedError