from datetime import datetime

from src.core.jarvis import Jarvis


class JarvisRuntime:
    """JARVIS'in çalışma ve dinlenme durumlarını yönetir."""

    BOOTING = "BOOTING"
    READY = "READY"
    WORKING = "WORKING"
    SLEEPING = "SLEEPING"
    STOPPED = "STOPPED"

    def __init__(self) -> None:
        self.jarvis = Jarvis()
        self.state = self.BOOTING
        self.started_at = datetime.now()
        self.completed_tasks = 0
        self.last_error: str | None = None

    def boot(self) -> None:
        self.state = self.READY
        self.sleep()

    def wake(self) -> None:
        self.state = self.READY

    def sleep(self) -> None:
        """
        Program kapanmaz. Yalnızca yeni görev bekleyen düşük işlem
        durumuna geçer.
        """
        self.state = self.SLEEPING

    def execute(self, message: str) -> str:
        self.wake()
        self.state = self.WORKING
        self.last_error = None

        try:
            result = self.jarvis.chat(message)
            self.completed_tasks += 1
            return result

        except Exception as error:
            self.last_error = str(error)
            return f"Görev sırasında hata oluştu: {error}"

        finally:
            self.sleep()

    def status(self) -> str:
        uptime = datetime.now() - self.started_at

        return (
            "=== JARVIS DURUMU ===\n"
            f"Durum: {self.state}\n"
            f"Tamamlanan görev: {self.completed_tasks}\n"
            f"Çalışma süresi: {str(uptime).split('.')[0]}\n"
            f"Son hata: {self.last_error or 'Yok'}"
        )

    def shutdown(self) -> None:
        self.state = self.STOPPED