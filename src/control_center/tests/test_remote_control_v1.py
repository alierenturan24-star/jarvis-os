from pathlib import Path

from src.control_center.server import load_or_create_token
from src.control_center.service import ControlCenterService
from src.control_center.store import ControlCenterStore


class JarvisStub:
    last_mission = None


class RuntimeStub:
    BOOTING = "BOOTING"
    STOPPED = "STOPPED"
    def __init__(self):
        self.state = "SLEEPING"
        self.jarvis = JarvisStub()
        self.completed_tasks = 2
        self.last_error = None
        self.last_mission_status = "completed"
        self.stop_requested = False
    def shutdown(self):
        self.state = self.STOPPED


def test_session_token_survives_restart_and_is_not_weak(tmp_path):
    path = tmp_path / "session.token"
    first = load_or_create_token(path)
    second = load_or_create_token(path)
    assert first == second and len(first) >= 32


def test_fresh_session_rotates_old_browser_token(tmp_path):
    path = tmp_path / "session.token"
    old = load_or_create_token(path)
    fresh = load_or_create_token(path, rotate=True)
    assert fresh != old and load_or_create_token(path) == fresh and len(fresh) >= 32


def test_startup_marks_active_mission_interrupted_and_preserves_state(tmp_path):
    store = ControlCenterStore(tmp_path / "state.json")
    def seed(state):
        state["missions"].append({"id": "m1", "status": "WORKING"})
        state["paper"]["cash"] = 9876
        state["engines"]["youtube"]["queue"].append({"id": "y1", "status": "DISPATCHED"})
        state["approvals"].append({"id": "a1", "status": "PENDING"})
    store.update(seed)
    ControlCenterService(RuntimeStub(), store)
    state = store.snapshot()
    assert state["missions"][0]["status"] == "INTERRUPTED"
    assert state["missions"][0]["recovery_required"] is True
    assert state["engines"]["youtube"]["queue"][0]["status"] == "INTERRUPTED"
    assert state["paper"]["cash"] == 9876 and state["approvals"][0]["status"] == "PENDING"


def test_phone_approval_audit_and_reject_do_not_stop_engine(tmp_path):
    runtime = RuntimeStub()
    service = ControlCenterService(runtime, ControlCenterStore(tmp_path / "state.json"))
    item = service.create_approval("finance_real_trade", {"need": "paper-qualified BTC", "why": "future infrastructure",
        "risk": "HIGH", "cost": 25, "expected_result": "approval record only"})
    result = service.decide_approval(item["id"], False, "Not acceptable from phone")
    assert result["status"] == "REJECTED" and result["decision_reason"] == "Not acceptable from phone"
    assert result["decision_source"] == "authenticated_control_center" and result["decided_at"]
    assert runtime.state != runtime.STOPPED


def test_health_and_notification_are_real_persisted_state(tmp_path):
    service = ControlCenterService(RuntimeStub(), ControlCenterStore(tmp_path / "state.json"))
    event = service.test_notification()
    health = service.health()
    assert health["backend_alive"] is True and health["runtime_state"] == "SLEEPING"
    assert health["finance"]["live_activation"] is False and health["public_exposure"] is False
    assert health["notifications"]["unread"] == 1
    capabilities = {item["id"]: item for item in health["capabilities"]}
    assert capabilities["command_pipeline"]["ready"] is True
    assert capabilities["finance"]["mode"] == "PAPER ONLY"
    assert capabilities["youtube_account"]["ready"] is False
    assert service.store.snapshot()["notifications"][-1]["id"] == event["id"]


def test_mobile_ui_contains_voice_health_approval_and_video_controls():
    html = Path("src/control_center/web/index.html").read_text(encoding="utf-8")
    js = Path("src/control_center/web/app.js").read_text(encoding="utf-8")
    css = Path("src/control_center/web/app.css").read_text(encoding="utf-8")
    assert all(value in html for value in ("backendKpi", "mic", "approvalList", "youtubeArtifacts", "financeCycle"))
    assert "source='text'" in js and "command('voice')" in js
    assert "decision_reason" in js and "loadYoutubeArtifacts" in js
    assert "@media(max-width:390px)" in css and "min-height:44px" in css


def test_startup_installer_defaults_to_plan_only_and_loopback():
    source = Path("tools/control_center_startup.ps1").read_text(encoding="utf-8")
    watchdog = Path("tools/start_control_center_watchdog.ps1").read_text(encoding="utf-8")
    assert "PLAN ONLY" in source and "-not $Install" in source
    assert "127.0.0.1" in watchdog and "0.0.0.0" not in watchdog
    assert "RestartDelaySeconds" in watchdog
    assert "-WorkingDirectory $ProjectRoot" in source
    assert "-PythonExecutable" in source and "--no-bootstrap-output" in watchdog
    assert "Test-ControlCenterHealth" in watchdog and "Test-PortListening" in watchdog
    assert "Start-Process" in watchdog and "& python" not in watchdog
    assert "main()" in Path("control_center.py").read_text(encoding="utf-8")


def test_one_click_launcher_is_local_non_admin_and_preserves_env():
    batch = Path("START_JARVIS.bat").read_text(encoding="utf-8")
    setup = Path("tools/setup_and_start.ps1").read_text(encoding="utf-8")
    assert "setup_and_start.ps1" in batch
    assert "127.0.0.1" in setup and "0.0.0.0" not in setup
    assert "Test-Path -LiteralPath $EnvironmentFile" in setup
    assert "Copy-Item -LiteralPath $EnvironmentExample" in setup
    assert "RunAs" not in setup and "Start-Process $url" in setup
    assert "--fresh-session" in setup
