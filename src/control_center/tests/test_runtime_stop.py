from src.core.runtime import JarvisRuntime


class ReturningJarvis:
    last_mission = None
    def chat(self, message): return "ok"


def test_stopped_runtime_does_not_execute_or_wake():
    runtime = JarvisRuntime.__new__(JarvisRuntime)
    runtime.jarvis = ReturningJarvis(); runtime.state = runtime.STOPPED
    runtime.stop_requested = True; runtime.completed_tasks = 0
    runtime.last_error = runtime.last_mission_status = None
    assert "durduruldu" in runtime.execute("goal")
    assert runtime.state == runtime.STOPPED and runtime.completed_tasks == 0
