from __future__ import annotations

from src.jobs.task_status import TaskStatus


def is_supporting_task(task) -> bool:
    return (task.metadata or {}).get("goal_critical") is False


def critical_failures(plan) -> list:
    return [task for task in plan.all_tasks() if task.status == TaskStatus.FAILED and not is_supporting_task(task)]


def supporting_failures(plan) -> list:
    return [task for task in plan.all_tasks() if task.status == TaskStatus.FAILED and is_supporting_task(task)]

