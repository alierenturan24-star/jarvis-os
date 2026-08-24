"""Run the concrete V1 acceptance goal and print machine-checkable evidence."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.jarvis import Jarvis
from src.mission.completion import evaluate_goal_completion


def main() -> None:
    jarvis = Jarvis()
    response = jarvis.chat("Almanya'daki çocuklar için YouTube çizgi film üret.")
    mission = jarvis.last_mission
    if mission is None:
        raise RuntimeError("Acceptance goal did not enter the mission path")

    completion = evaluate_goal_completion(mission)
    print("STATUS=", mission.status.value)
    print("DEPARTMENTS=", mission.departments)
    print("CAP_GAPS=", mission.capability_gaps)
    print("ARTIFACTS=", mission.artifact_paths)
    print("COMPLETE=", completion.satisfied)
    print("REMAINING=", [item.requirement.remaining for item in completion.missing])
    print(
        "TASKS=",
        [
            (
                task.agent,
                task.status.value,
                task.metadata.get("artifact_path", ""),
                str(task.error or "")[:160],
            )
            for task in mission.tasks
        ],
    )
    print("REPORT_TAIL=", response[-3000:])


if __name__ == "__main__":
    main()
