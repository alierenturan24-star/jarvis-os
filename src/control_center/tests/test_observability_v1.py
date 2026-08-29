from src.config.settings import Settings
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


# Phase 10: Control Center media provider visibility -- truthful status,
# no secrets, and an unconfigured NVIDIA/LTX must not degrade overall
# system_status (they are opt-in foundations, not core text LLM routing).
def test_media_providers_reports_truthful_status_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "")
    monkeypatch.setattr(Settings, "LTX_API_KEY", "")
    # AIML (src.providers.aiml_media_provider) is a fourth real
    # text_to_image candidate -- must also be disabled here, otherwise a
    # real configured key in the running environment would make its row
    # AVAILABLE and break the blanket "neither key is configured" assertion
    # below (which applies to every row, not just nvidia/ltx).
    monkeypatch.setattr(Settings, "FAL_API_KEY", "")
    monkeypatch.setattr(Settings, "AIML_API_KEY", "")
    rows = service(tmp_path).read_model.media_providers()

    providers = {row["provider"] for row in rows}
    assert {"nvidia", "ltx"} <= providers
    for row in rows:
        assert row["status"] in {"AVAILABLE", "AUTH_REQUIRED", "QUOTA_BLOCKED", "UNAVAILABLE"}
        assert row["status"] != "AVAILABLE"  # neither key is configured in this test
    # "NVIDIA_API_KEY not configured" is a truthful, non-secret reason (the
    # env VAR NAME, not a value) -- only actual key/token VALUES must never
    # appear, checked directly against a real configured value below.
    serialized = str(rows).casefold()
    assert "authorization" not in serialized and "bearer " not in serialized


def test_media_providers_reports_available_when_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "super-secret-value-should-not-leak")
    rows = service(tmp_path).read_model.media_providers()

    nvidia_row = next(row for row in rows if row["provider"] == "nvidia")
    assert nvidia_row["status"] == "AVAILABLE"
    assert nvidia_row["cost_class"] == "paid"
    assert "super-secret-value-should-not-leak" not in str(rows)


def test_dashboard_includes_media_provider_health_without_degrading_status(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "")
    monkeypatch.setattr(Settings, "LTX_API_KEY", "")
    monkeypatch.setattr(Settings, "FAL_API_KEY", "")
    monkeypatch.setattr(Settings, "AIML_API_KEY", "")
    current = service(tmp_path)
    dashboard = current.read_model.dashboard()

    assert "media_provider_health" in dashboard
    assert dashboard["media_provider_health"]["available"] == 0
    # Unconfigured media providers alone must not flip the CORE system
    # status to DEGRADED -- only real runtime/text-provider issues should.
    assert dashboard["system_status"] in {"ONLINE", "DEGRADED", "OFFLINE"}


# Q/R: Control Center exposes fal FLUX and LTX-2.5 too, with real
# provider/model identity and no credential material -- and health_status
# explains WHY a provider was deprioritized (bounded cooldown), distinct
# from plain configured/auth status.
def test_media_providers_includes_fal_and_ltx_2_5_models_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "")
    monkeypatch.setattr(Settings, "LTX_API_KEY", "super-secret-shared-fal-key")
    monkeypatch.setattr(Settings, "FAL_API_KEY", "")
    monkeypatch.chdir(tmp_path)
    rows = service(tmp_path).read_model.media_providers()

    providers = {row["provider"] for row in rows}
    assert {"nvidia", "fal", "ltx"} <= providers
    models = {row["model"] for row in rows}
    assert "lightricks/ltx-2.5/text-to-video/fast" in models
    assert "lightricks/ltx-2.5/image-to-video/fast" in models
    fal_row = next(row for row in rows if row["provider"] == "fal")
    assert fal_row["status"] == "AVAILABLE"  # unlocked via the shared fal.ai LTX_API_KEY
    for row in rows:
        assert "health_status" in row and row["health_status"] in {"HEALTHY", "COOLDOWN"}
        assert "health_reason" in row
    assert "super-secret-shared-fal-key" not in str(rows)


def test_media_providers_health_explains_recent_cooldown(tmp_path, monkeypatch):
    from src.providers.execution_history import ProviderExecutionHistory

    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.chdir(tmp_path)
    history = ProviderExecutionHistory()
    for _ in range(3):
        history.record(task_type="text_to_image", provider="nvidia", success=False,
                        fallback_used=False, duration_seconds=60.0, cost_class="paid")

    rows = service(tmp_path).read_model.media_providers()

    nvidia_row = next(row for row in rows if row["provider"] == "nvidia")
    assert nvidia_row["status"] == "AVAILABLE"  # auth still configured
    assert nvidia_row["health_status"] == "COOLDOWN"  # but recently unhealthy
    assert "consecutive recent failures" in nvidia_row["health_reason"]
    assert nvidia_row["cooldown_until"] is not None


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
