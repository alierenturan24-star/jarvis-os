from __future__ import annotations

from src.control_center.service import ControlCenterService
from src.control_center.store import ControlCenterStore


def service(tmp_path):
    return ControlCenterService(store=ControlCenterStore(tmp_path / "state.json"))


class _FakeMissionWithResolutions:
    def __init__(self, capability_requirements, capability_resolutions):
        self.tasks = []
        self.capability_requirements = capability_requirements
        self.capability_resolutions = capability_resolutions


# Phase 11-P: Control Center explains, per fine-grained capability, who
# resolved it (or didn't) and why -- reusing the existing sanitize()-wrapped
# read-model pattern (see media_providers()).
def test_capability_resolutions_read_model_shape_and_sanitization(tmp_path):
    requirements = [
        {"name": "web_research", "necessity": "REQUIRED", "alternatives": [["web_research"]], "reason": ""},
        {"name": "tts", "necessity": "REQUIRED", "alternatives": [["tts"]], "reason": ""},
    ]
    resolutions = [
        {"capability": "web_research", "status": "READY", "resolved_by": "gemini", "cost_class": "free",
         "health": "HEALTHY", "source": "text_provider",
         "reason": "Selected 'gemini' for 'web_research'. api_key=should-not-leak"},
        {"capability": "tts", "status": "CAPABILITY_GAP", "resolved_by": "", "cost_class": "unknown",
         "health": "unknown", "source": "none", "reason": "No provider, registry entry, or in-flight candidate satisfies 'tts'."},
    ]
    current = service(tmp_path)
    current.runtime.jarvis.last_mission = _FakeMissionWithResolutions(requirements, resolutions)

    rows = current.read_model.capability_resolutions()

    by_capability = {row["capability"]: row for row in rows}
    assert by_capability["web_research"]["necessity"] == "REQUIRED"
    assert by_capability["web_research"]["status"] == "READY"
    assert by_capability["web_research"]["resolved_by"] == "gemini"
    assert by_capability["tts"]["status"] == "CAPABILITY_GAP"
    assert by_capability["tts"]["source"] == "none"
    assert "should-not-leak" not in str(rows)
    for key in ("capability", "necessity", "status", "resolved_by", "cost_class", "health", "source", "reason"):
        assert key in by_capability["web_research"]


def test_capability_resolutions_empty_when_no_live_mission(tmp_path):
    assert service(tmp_path).read_model.capability_resolutions() == []


def test_capability_resolutions_route_is_registered():
    from src.control_center.server import ControlCenterHandler
    import inspect

    source = inspect.getsource(ControlCenterHandler.do_GET)
    assert "/api/capability-resolutions" in source
