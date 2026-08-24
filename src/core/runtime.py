from datetime import datetime
import traceback
import os

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
        self.last_error_context: str | None = None
        self.last_mission_status: str | None = None
        self.stop_requested = False
        chat_worker = self.jarvis.agent_router.registry.get("chat")
        if chat_worker is not None:
            chat_worker.runtime_context_provider = self.context_snapshot

    def context_snapshot(self) -> dict:
        now = datetime.now().astimezone()
        return {
            "local_datetime": now.isoformat(timespec="seconds"),
            "local_date": now.date().isoformat(),
            "timezone": str(now.tzinfo),
            "runtime_state": self.state,
            "runtime_pid": os.getpid(),
            "runtime_started_at": self.started_at.astimezone().isoformat(timespec="seconds"),
            "completed_tasks": self.completed_tasks,
            "last_error": self.last_error,
            "last_mission_status": self.last_mission_status,
        }

    def boot(self) -> None:
        self.stop_requested = False
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

    def execute(self, message: str, execution_hints: dict | None = None) -> str:
        if self.stop_requested or self.state == self.STOPPED:
            return "JARVIS durduruldu; yeni görev kabul edilmiyor."
        self.wake()
        self.state = self.WORKING
        self.last_error = None
        self.last_error_context = None

        try:
            result = self.jarvis.chat(message, execution_hints=execution_hints)
            mission = getattr(self.jarvis, "last_mission", None)
            self.last_mission_status = mission.status.value if mission is not None else None
            if mission is None or self.last_mission_status == "completed":
                self.completed_tasks += 1
            return result

        except Exception as error:
            self.last_error = str(error)
            self.last_error_context = traceback.format_exc()
            return f"Görev sırasında hata oluştu: {error}"

        finally:
            if not self.stop_requested:
                self.sleep()

    def status(self) -> str:
        uptime = datetime.now() - self.started_at

        return (
            "=== JARVIS DURUMU ===\n"
            f"Durum: {self.state}\n"
            f"Tamamlanan görev: {self.completed_tasks}\n"
            f"Çalışma süresi: {str(uptime).split('.')[0]}\n"
            f"Son hata: {self.last_error or 'Yok'}"
            f"\nSon mission durumu: {self.last_mission_status or 'Yok'}"
        )

    def shutdown(self) -> None:
        self.stop_requested = True
        self.state = self.STOPPED
