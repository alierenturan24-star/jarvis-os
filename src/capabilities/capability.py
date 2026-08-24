from dataclasses import dataclass, field


@dataclass
class Capability:

    id: str

    name: str

    version: str

    category: str

    source: str

    score: int = 0

    enabled: bool = True
    status: str = "DISCOVERED"
    access_method: str = "MANUAL_ONLY"
    available: bool = False
    requires_approval: bool = False
    last_verified_at: str | None = None
    success_count: int = 0
    failure_count: int = 0
    last_used_at: str | None = None
    metadata: dict = field(default_factory=dict)
