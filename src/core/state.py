from dataclasses import dataclass, field
from typing import Any


@dataclass
class JarvisState:

    user_message: str = ""

    goal: str = ""

    current_agent: str = "chat"

    current_task: str = ""

    result: Any = None

    error: str = ""

    finished: bool = False

    metadata: dict = field(default_factory=dict)