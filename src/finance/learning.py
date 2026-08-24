from __future__ import annotations

from typing import Any

from src.agents.base_agent import BaseAgent
from src.jobs.task import Task


class FinanceLearningAgent(BaseAgent):
    """Observe persisted finance evidence without trading or qualifying."""

    def __init__(self, store=None) -> None:
        super().__init__("Finance Learning Agent")
        self.store = store

    def execute(self, task: Task) -> str:
        from src.control_center.store import utc_now
        if self.store is None:
            from src.control_center.store import ControlCenterStore
            self.store = ControlCenterStore()
        exploration = self.store.snapshot().get("finance_exploration", {})
        candidates: dict[str, dict[str, Any]] = exploration.get("candidates", {})
        rejected = [row for row in candidates.values() if row.get("qualification_result") == "REJECTED"]
        qualified = [row for row in candidates.values() if row.get("qualification_result") == "QUALIFIED"]
        failure_counts: dict[str, int] = {}
        for row in rejected:
            for reason in row.get("rejection_reasons", []):
                failure_counts[reason] = failure_counts.get(reason, 0) + 1
        next_space = []
        if failure_counts:
            next_space.append("prefer untested parameter variations; retain asset/timeframe/regime scope")
        if any("trade count" in reason.casefold() for reason in failure_counts):
            next_space.append("test a new timeframe or data window to increase observations")
        if any("oos" in reason.casefold() for reason in failure_counts):
            next_space.append("prioritize OOS-stable variations without global family blacklisting")
        learning = {"learned_at": utc_now(), "observed_candidates": len(candidates),
                    "rejected": len(rejected), "qualified": len(qualified),
                    "failure_reasons": failure_counts, "next_exploration": next_space,
                    "learning_persisted": True, "can_qualify": False, "live_activation": False}

        def persist(state: dict[str, Any]) -> None:
            target = state.setdefault("finance_exploration", {"candidates": {}, "runs": []})
            target["last_learning"] = learning
            target["next_exploration"] = next_space
        self.store.update(persist)
        task.metadata["report"] = learning
        return (f"Finance learning persisted: {len(candidates)} candidates observed, "
                f"{len(rejected)} rejected, {len(qualified)} qualified; LIVE disabled.")
