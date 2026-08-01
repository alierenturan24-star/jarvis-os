from dataclasses import dataclass


@dataclass
class Task:

    agent: str

    action: str

    target: str = ""

    status: str = "waiting"