import json
from pathlib import Path

from src.core.runtime import JarvisRuntime
from src.mission.completion import evaluate_goal_completion


GOAL = ("Finance Engine'i PAPER araştırma modunda çalıştır. Bounded exploration ile yeni strateji "
        "adayları keşfet. Farklı likit asset, zaman dilimi ve piyasa regime'lerinde gerçek public "
        "market data ile backtest ve OOS doğrulaması yap. Sonuçları geçmiş performans hafızasına "
        "kaydet; başarısız adaylardan öğren. Qualified strateji yoksa işlem açma. Gerçek para kullanma.")


def run_once():
    runtime = JarvisRuntime()
    runtime.boot()
    output = runtime.execute(GOAL)
    mission = runtime.jarvis.last_mission
    finance = next(task for task in mission.tasks if task.agent == "finance")
    learning = next(task for task in mission.tasks if task.agent == "learning")
    lab = finance.metadata["report"]["strategy_lab"]
    return {"status": mission.status.value,
            "finance_target": finance.target,
            "missing": [item.requirement.name for item in evaluate_goal_completion(mission).missing],
            "finance_status": finance.status.value, "finance_error": finance.error,
            "finance_report_keys": sorted(finance.metadata.get("report", {})),
            "lab_keys": sorted(lab), "lab_value": lab if not lab.get("candidates") else None,
            "candidate_ids": [row["candidate_id"] for row in lab["candidates"]
                              if row.get("baseline_or_new") == "new"],
            "baseline_count": sum(row.get("baseline_or_new") == "baseline" for row in lab["candidates"]),
            "assets": lab.get("assets_tested"), "timeframes": lab.get("timeframes_tested"),
            "regimes": lab.get("regimes_tested"), "decision": lab.get("bounded_exploration_outcome"),
            "learning": learning.metadata.get("report"), "live_activation": lab.get("live_activation"),
            "output_tail": output[-500:]}


if __name__ == "__main__":
    first = run_once()
    second = run_once()  # new Runtime instance: process/reload-equivalent state load
    state = json.loads(Path("workspace/control_center/state.json").read_text(encoding="utf-8"))
    print(json.dumps({"mission_1": first, "mission_2": second,
                      "history_candidates": sorted(state["finance_exploration"]["candidates"]),
                      "repeated": sorted(set(first["candidate_ids"]) & set(second["candidate_ids"]))},
                     ensure_ascii=False, indent=2))
