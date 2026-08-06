from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ExecutableWorker(Protocol):
    def execute(self, task: Any) -> Any:
        """Execute a task and return a result."""


@dataclass(frozen=True)
class WorkerRegistration:
    name: str
    worker: ExecutableWorker
    capabilities: frozenset[str] = field(default_factory=frozenset)
    aliases: frozenset[str] = field(default_factory=frozenset)
    priority: int = 0


class WorkerRegistry:
    """Registers and resolves JARVIS workers by name, alias or capability."""

    def __init__(self) -> None:
        self._workers: dict[str, WorkerRegistration] = {}
        self._aliases: dict[str, str] = {}

    @staticmethod
    def _normalize(value: str) -> str:
        return value.casefold().strip()

    def register(
        self,
        name: str,
        worker: ExecutableWorker,
        *,
        capabilities: list[str] | tuple[str, ...] | set[str] = (),
        aliases: list[str] | tuple[str, ...] | set[str] = (),
        priority: int = 0,
        replace: bool = False,
    ) -> WorkerRegistration:
        normalized_name = self._normalize(name)

        if not normalized_name:
            raise ValueError("Worker adı boş olamaz.")

        if normalized_name in self._workers and not replace:
            raise ValueError(f"Worker zaten kayıtlı: {normalized_name}")

        normalized_aliases = frozenset(
            self._normalize(alias) for alias in aliases if self._normalize(alias)
        )
        normalized_capabilities = frozenset(
            self._normalize(capability)
            for capability in capabilities
            if self._normalize(capability)
        )

        registration = WorkerRegistration(
            name=normalized_name,
            worker=worker,
            capabilities=normalized_capabilities,
            aliases=normalized_aliases,
            priority=priority,
        )

        if replace and normalized_name in self._workers:
            self.unregister(normalized_name)

        self._workers[normalized_name] = registration

        for alias in normalized_aliases:
            existing = self._aliases.get(alias)
            if existing is not None and existing != normalized_name:
                raise ValueError(f"Takma ad zaten kullanılıyor: {alias}")
            self._aliases[alias] = normalized_name

        return registration

    def unregister(self, name: str) -> bool:
        normalized_name = self._normalize(name)
        registration = self._workers.pop(normalized_name, None)

        if registration is None:
            return False

        for alias in registration.aliases:
            self._aliases.pop(alias, None)

        return True

    def get(self, name_or_alias: str) -> ExecutableWorker | None:
        key = self._normalize(name_or_alias)
        resolved_name = self._aliases.get(key, key)
        registration = self._workers.get(resolved_name)
        return registration.worker if registration else None

    def registration(self, name_or_alias: str) -> WorkerRegistration | None:
        key = self._normalize(name_or_alias)
        resolved_name = self._aliases.get(key, key)
        return self._workers.get(resolved_name)

    def find(self, capability: str) -> list[WorkerRegistration]:
        normalized_capability = self._normalize(capability)
        matches = [
            registration
            for registration in self._workers.values()
            if normalized_capability in registration.capabilities
        ]
        return sorted(matches, key=lambda item: item.priority, reverse=True)

    def best(self, capability: str) -> ExecutableWorker | None:
        matches = self.find(capability)
        return matches[0].worker if matches else None

    def names(self) -> list[str]:
        return sorted(self._workers)

    def all(self) -> list[WorkerRegistration]:
        return sorted(
            self._workers.values(),
            key=lambda item: (-item.priority, item.name),
        )
