from src.mission.goal_spec import parse_goal_spec
from src.mission.mission_engine import MissionEngine
from src.mission.models import MissionType
from src.planner.planner import Planner


def test_named_project_goal_builds_one_mission_and_autonomous_subplan():
    engine = MissionEngine()
    mission = engine.create_mission("Agent-Reach'i araştır ve Jarvis için gerçekten faydalıysa değerlendir.")

    assert mission.target.requested_name == "Agent-Reach"
    assert {"research", "github", "browser", "evaluation"}.issubset(mission.departments)
    assert mission.goal.startswith("Agent-Reach")


def test_constraints_and_output_are_not_tasks_or_finance_routing():
    message = "Agent-Reach'i araştır. Kurma. Para harcama. Kısa sonuç ver."
    spec = parse_goal_spec(message)
    mission = MissionEngine().create_mission(message)

    assert spec.goal == "Agent-Reach'i araştır"
    assert spec.constraints == ("Kurma", "Para harcama")
    assert spec.output_preferences == ("Kısa sonuç ver",)
    assert "finance" not in mission.departments
    tasks = Planner().build(message)
    assert len(tasks) == 1
    assert tasks[0].agent == "research"


def test_multiline_paste_is_one_legacy_workflow_task():
    message = "Agent-Reach'i araştır\nBu yalnız araştırma ve değerlendirme görevidir.\nSon rapor:\nKARAR:"
    tasks = Planner().build(message)

    assert len(tasks) == 1
    assert tasks[0].target == message


def test_youtube_goal_derives_media_gap_and_discovery_without_procedure():
    mission = MissionEngine().create_mission("Almanya'daki çocuklar için YouTube çizgi film üret.")

    assert mission.mission_type == MissionType.YOUTUBE
    assert {"research", "media", "automation"}.issubset(mission.departments)
    assert "media_artifact" in mission.required_capabilities
    assert "media_artifact" in mission.current_capabilities
    assert "media_artifact" not in mission.capability_gaps
    assert mission.discovery_required is False


def test_bitcoin_finance_routing_is_preserved():
    mission = MissionEngine().create_mission("Bitcoin neden düştü?")

    assert mission.mission_type == MissionType.FINANCE
    assert "finance" in mission.departments
