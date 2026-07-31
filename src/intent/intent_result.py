from dataclasses import dataclass, field
from typing import Any


@dataclass
class IntentResult:
    """Kullanıcının isteğinin analiz sonucunu temsil eder."""

    name: str
    confidence: float = 1.0
    parameters: dict[str, Any] = field(default_factory=dict)

    @property
    def is_tool_intent(self) -> bool:
        return self.name != "chat"