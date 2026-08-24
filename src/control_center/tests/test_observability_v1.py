from src.control_center.observability import ControlCenterReadModel, sanitize
from src.control_center.service import ControlCenterService
from src.control_center.store import ControlCenterStore


def service(tmp_path):
    return ControlCenterService(store=ControlCenterStore(tmp_path / "state.json"))


def test_dashboard_workers_and_empty_states_use_real_sources(tmp_path):
    current = service(tmp_path)
    dashboard = current.read_model.dashboard()
    workers = current.read_model.workers()
    assert dashboard["system_status"] in {"ONLINE", "DEGRADED", "OFFLINE"}
    assert {"ResearchAgent", "FinanceAgent", "MediaAgent"} <= {row["name"] for row in workers}
    assert current.read_model.costs()["available"] is False
    assert current.read_model.tasks() == []


def test_provider_contract_never_exposes_credentials(tmp_path):
    payload = current = service(tmp_path).read_model.providers()
    assert current
    serialized = str(payload).casefold()
    assert "api_key" not in serialized and "authorization" not in serialized


def test_finance_defaults_to_simulation_and_youtube_is_disconnected(tmp_path):
    model = service(tmp_path).read_model
    assert model.finance()["mode"] == "PAPER / SIMULATION"
    assert model.finance()["live_execution"] is False
    assert model.youtube()["status"] == "NOT CONNECTED"


def test_log_sanitizer_redacts_nested_and_inline_secrets(tmp_path):
    value = sanitize({"Authorization": "Bearer abc123", "event": "token=abc123", "nested": {"password": "pw"}})
    assert value["Authorization"] == "[REDACTED]"
    assert "abc123" not in str(value) and "pw" not in str(value)
    current = service(tmp_path)
    current.activity("PROVIDER", "Authorization: Bearer secret-value")
    assert "secret-value" not in str(ControlCenterReadModel(current).logs())


def test_frontend_contains_control_center_v1_views():
    from src.control_center.server import WEB_ROOT

    script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    for label in ("ÇALIŞANLAR", "ARAŞTIRMA", "AI SAĞLAYICILARI", "MALİYETLER", "SİSTEM / LOGLAR"):
        assert label in script


class _FakeMissionWithTasks:
    def __init__(self, tasks):
        self.tasks = tasks


def test_claude_code_delegation_fields_are_surfaced_and_secrets_redacted(tmp_path):
    from src.jobs.task import Task

    task = Task(
        title="[coding] fix bug", agent="coding", action="edit", target="fix bug",
        metadata={
            "delegated_to": "claude_code",
            "status": "DONE",
            "files_changed": ["src/example.py"],
            "files_changed_count": 1,
            "tests_executed": True,
            "result_summary": "Değişiklik yapıldı. api_key=abc123secret",
            "error_summary": None,
            "approval_required": False,
        },
    )

    current = service(tmp_path)
    current.runtime.jarvis.last_mission = _FakeMissionWithTasks([task])

    rows = current.read_model.tasks()

    assert len(rows) == 1
    row = rows[0]
    assert row["delegated_to"] == "claude_code"
    assert row["files_changed"] == ["src/example.py"]
    assert row["files_changed_count"] == 1
    assert row["tests_executed"] is True
    assert "abc123secret" not in str(row)


def test_non_delegated_coding_task_has_no_claude_code_fields(tmp_path):
    from src.jobs.task import Task

    task = Task(
        title="[coding] write a function", agent="coding", action="write", target="write a function",
        metadata={"preferred_ai_provider": "codex"},
    )

    current = service(tmp_path)
    current.runtime.jarvis.last_mission = _FakeMissionWithTasks([task])

    row = current.read_model.tasks()[0]
    assert "delegated_to" not in row
