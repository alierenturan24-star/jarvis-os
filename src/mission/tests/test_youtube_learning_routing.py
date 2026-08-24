from src.mission.department_orchestrator import DepartmentOrchestrator


def test_history_informed_authored_youtube_production_skips_investigative_chain():
    goal = (
        "Almanya'daki çocuklar için yeni hikâyeli ikinci YouTube çizgi filmi üret. "
        "Kalıcı YouTube learning planını uygula; önceki script ve sahneleri tekrarlama."
    )
    departments = DepartmentOrchestrator().select_departments(goal)
    assert "media" in departments
    assert not ({"research", "github", "browser"} & set(departments))
