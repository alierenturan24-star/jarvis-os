from dataclasses import dataclass, field


@dataclass
class Mission:

    title: str

    objective: str

    priority: int = 50

    tasks: list = field(default_factory=list)

    assigned_agents: list = field(default_factory=list)

    status: str = "WAITING"