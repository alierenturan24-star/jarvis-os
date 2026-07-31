from abc import ABC, abstractmethod


class BaseProvider(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Verilen komuta cevap üretir."""
        raise NotImplementedError