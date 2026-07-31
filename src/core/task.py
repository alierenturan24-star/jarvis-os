from dataclasses import dataclass, field
from typing import List
import uuid


@dataclass
class Task:

    title: str

    description: str

    status: str = "waiting"

    priority: int = 1

    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    subtasks: List["Task"] = field(default_factory=list)

    def complete(self):

        self.status = "completed"

    def add_subtask(self, task):

        self.subtasks.append(task)