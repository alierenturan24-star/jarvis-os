from src.mission.department import Department, classify_mission_type, detect_mission_type
from src.mission.models import Mission, MissionStatus, MissionType, ResourcePlan


def __getattr__(name: str):
    """Load orchestration exports only when callers request them.

    Importing a lightweight mission helper (for example ``completion``) must
    not construct the complete department graph.  Keeping these two public
    re-exports lazy also preserves ``from src.mission import MissionEngine``.
    """
    if name == "DepartmentOrchestrator":
        from src.mission.department_orchestrator import DepartmentOrchestrator

        return DepartmentOrchestrator
    if name == "MissionEngine":
        from src.mission.mission_engine import MissionEngine

        return MissionEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "Mission",
    "MissionStatus",
    "MissionType",
    "ResourcePlan",
    "Department",
    "classify_mission_type",
    "detect_mission_type",
    "DepartmentOrchestrator",
    "MissionEngine",
]
