from dataclasses import dataclass


@dataclass
class TaskResult:

    task: str

    success: bool

    output: str