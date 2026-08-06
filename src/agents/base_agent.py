from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from src.agents.agent_result import AgentResult


class BaseAgent(ABC):
    """Tüm JARVIS ajanlarının uyması gereken ortak sözleşme.

    ``task`` parametresi kasıtlı olarak ``Any``: hem
    ``src.planner.task.Task`` (mevcut ``AgentRouter`` bunu kullanır) hem
    de ``src.jobs.task.Task`` (Task Engine) ile duck-typing üzerinden
    (``.target``/``.action``/``.agent`` alanları) çalışır — bu dosyanın
    kapsamı dışındaki paketlere sıkı bağımlılık eklenmez.
    """

    def __init__(self, name: str = "Base Agent") -> None:
        self.name = name

    @abstractmethod
    def execute(self, task: Any) -> str:
        """Verilen görevi çalıştırır ve sonucu metin olarak döndürür.

        Geriye dönük uyumluluk için dönüş tipi ``str`` kalır — mevcut
        ``AgentRouter`` bu değeri doğrudan ``task.result``'a yazıyor.
        Yapılandırılmış sonuç için ``run()`` kullanın.
        """
        raise NotImplementedError

    def supports(self, task: Any) -> bool:
        """Bu ajanın verilen görevi üstlenip üstlenemeyeceğini bildirir.

        Varsayılan olarak her görevi destekler — bugüne kadar yönlendirme
        kararı ``WorkerRegistry``'nin capability/priority eşleşmesiyle
        veriliyordu, bu davranış değişmedi. Alt sınıflar daha spesifik
        bir kural için override edebilir.
        """
        return True

    def health(self) -> dict:
        """Ajanın temel sağlık/durum bilgisini döndürür."""
        return {"agent": self.name, "available": True}

    def verify(self, result: Any) -> bool:
        if result is None:
            return False

        if isinstance(result, str):
            if result.strip() == "":
                return False

            if result.casefold().startswith(("hata", "error")):
                return False

        return True

    def plan(self, task: Any) -> Any:
        return task

    def report(self, result: Any) -> Any:
        return result

    def run(self, task: Any) -> AgentResult:
        """``execute()``'i çalıştırıp standart ``AgentResult``'a sarar.

        Task Engine (``src/jobs``) ile uyumluluk için ortak çağırma
        noktasıdır; ``to_handler()`` bunun üzerine kuruludur.
        """
        try:
            output = self.execute(task)
            success = self.verify(output)

            return AgentResult(
                agent=self.name,
                success=success,
                output=output if success else None,
                error="" if success else str(output),
            )
        except Exception as error:
            return AgentResult(
                agent=self.name,
                success=False,
                output=None,
                error=str(error),
            )

    def to_handler(self) -> Callable[[Any], AgentResult]:
        """``src.jobs.task.Task.handler`` olarak kullanılabilecek bir
        çağrılabilir döndürür (Task Engine entegrasyon noktası)."""
        return self.run
