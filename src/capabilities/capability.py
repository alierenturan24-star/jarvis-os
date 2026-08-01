from dataclasses import dataclass


@dataclass
class Capability:

    id: str

    name: str

    version: str

    category: str

    source: str

    score: int = 0

    enabled: bool = True