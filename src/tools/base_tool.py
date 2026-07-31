from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """
    Jarvis araçlarının ortak temel sınıfı.

    Bütün araçlar bu sınıftan türetilir.
    """

    def __init__(
        self,
        name: str,
        description: str,
        requires_confirmation: bool = False,
    ):
        self.name = name
        self.description = description
        self.requires_confirmation = requires_confirmation

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        """
        Aracın yapacağı işlemi çalıştırır.
        """
        raise NotImplementedError

    def get_info(self) -> dict:
        """
        Araç hakkında temel bilgileri döndürür.
        """
        return {
            "name": self.name,
            "description": self.description,
            "requires_confirmation": self.requires_confirmation,
        }