from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Conflict:
    """JARVIS mimarisiyle harici repo arasında bulunan tek bir çakışma.

    ``type``: "same_class_name" | "same_module_name" | "provider_conflict" |
    "tool_conflict" | "duplicate_functionality" | "license_problem" |
    "dependency_conflict"
    ``severity``: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    """

    type: str
    description: str
    severity: str


@dataclass
class IntegrationPlan:
    """Bir reponun JARVIS'e entegrasyonu için üretilen, ÇALIŞTIRILMAMIŞ
    (yalnızca planlanmış) yol haritası.

    ``IntegrationPlanner.analyze()`` bu tipi üretir. Girdi olarak
    ``src.sandbox.models.SandboxResult`` (statik analiz bulguları) ve
    ``src.evaluation.models.RepoEvaluation`` (uygunluk/risk/alaka) alır;
    hiçbir kod DEĞİŞTİRMEZ, hiçbir dosya KOPYALAMAZ, hiçbir MERGE yapmaz.
    """

    repository_name: str
    repository_url: str

    target_module: str
    target_package: str
    integration_strategy: str

    estimated_files: int
    estimated_changes: int
    estimated_risk: str
    breaking_change_probability: float

    dependencies_required: list[str] = field(default_factory=list)
    license_notes: str = ""

    merge_ready: bool = False
    conflicts: list[Conflict] = field(default_factory=list)

    required_tests: list[str] = field(default_factory=list)
    migration_steps: list[str] = field(default_factory=list)
    rollback_plan: str = ""

    summary: str = ""
