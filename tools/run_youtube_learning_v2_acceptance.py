"""UTF-8 live acceptance for the second, history-informed production."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.control_center.store import ControlCenterStore
from src.core.jarvis import Jarvis
from src.media.learning import YouTubeLearningAgent
from src.mission.completion import evaluate_goal_completion

GOAL = (
    "Almanya'daki çocuklar için 60 saniyelik, Almanca seslendirmeli, tutarlı "
    "Leni karakteri ve gerçek body motion içeren yeni hikâyeli ikinci YouTube "
    "çizgi filmi üret. Kalıcı YouTube learning planını uygula; önceki script "
    "ve sahneleri tekrarlama. Yayınlama."
)

agent = YouTubeLearningAgent()
agent.refresh_character_memory()
before = ControlCenterStore().snapshot()["youtube_learning"]["productions"]
jarvis = Jarvis()
response = jarvis.chat(GOAL)
mission = jarvis.last_mission
completion = evaluate_goal_completion(mission)
after = ControlCenterStore().snapshot()["youtube_learning"]
print("STATUS=", mission.status.value)
print("DEPARTMENTS=", mission.departments)
print("COMPLETE=", completion.satisfied)
print("REMAINING=", [item.requirement.remaining for item in completion.missing])
print("BEFORE_COUNT=", len(before), "AFTER_COUNT=", len(after["productions"]))
print("ARTIFACTS=", mission.artifact_paths)
for row in after["productions"][-2:]:
    print("PRODUCTION=", row["production_id"], row["quality"], row["fingerprints"])
    print("VIDEO=", row["artifact"]["final_video_path"], "THUMBNAIL=", row["thumbnail"])
print("CHARACTER=", after["characters"].get("Leni"))
print("REPORT_TAIL=", response[-1000:])
