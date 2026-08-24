from src.core.ceo import CEO
from src.mission.models import Mission


def test_internal_error_records_traceback_and_mission_context():
    ceo = CEO(); mission = Mission(title="telemetry mission")
    try:
        raise ValueError("safe failure")
    except ValueError as error:
        ceo._record_internal_error(mission, "mission_self_check", error)
    saved = mission.error_context[-1]
    assert saved["exception_type"] == "ValueError"
    assert saved["message"] == "safe failure"
    assert "Traceback" in saved["traceback"]
    assert saved["component"] == "mission_self_check"
    assert saved["timestamp"]
