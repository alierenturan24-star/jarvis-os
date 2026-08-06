from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SandboxStatus(str, Enum):
    """Bir sandbox oturumunun yaşam döngüsü boyunca alabileceği durumlar."""

    CREATED = "created"
    CLONING = "cloning"
    ANALYZING = "analyzing"
    READY_FOR_REVIEW = "ready_for_review"
    BLOCKED = "blocked"
    FAILED = "failed"
    CLEANED = "cleaned"


class SandboxMode(str, Enum):
    """İki mod:

    ``STATIC_ANALYSIS`` — güvenli varsayılan. Repo indirilebilir ama
    hiçbir kod çalıştırılmaz, hiçbir bağımlılık kurulmaz.

    ``ISOLATED_EXECUTION`` — yalnızca güvenli izolasyon aracı (Docker)
    mevcutsa VE açık onay verilmişse çözümlenir; aksi halde otomatik
    olarak ``STATIC_ANALYSIS``'a döner. Bu sprint kapsamında gerçek
    izole çalıştırma UYGULANMAZ — mod seçilse bile pipeline yalnızca
    statik analiz yapar (bkz. ``SandboxManager._resolve_mode``).
    """

    STATIC_ANALYSIS = "static_analysis"
    ISOLATED_EXECUTION = "isolated_execution"


@dataclass
class SandboxResult:
    """Bir sandbox oturumunun tam durumu ve analiz çıktısı.

    ``SandboxManager``'ın her adımı (``clone_repository``, ``inspect``,
    ``detect_manifests``, ``detect_commands``, ``scan_security``,
    ``evaluate_risk``) bu nesneyi YERİNDE günceller ve döndürür.
    """

    repository_name: str
    repository_url: str
    sandbox_path: Optional[str] = None
    status: SandboxStatus = SandboxStatus.CREATED
    mode: SandboxMode = SandboxMode.STATIC_ANALYSIS

    files_scanned: int = 0
    total_size_mb: float = 0.0
    detected_language: str = ""

    detected_manifests: list[str] = field(default_factory=list)
    detected_test_commands: list[str] = field(default_factory=list)
    detected_install_commands: list[str] = field(default_factory=list)

    suspicious_files: list[str] = field(default_factory=list)
    suspicious_patterns: list[str] = field(default_factory=list)

    network_risk: str = "LOW"
    execution_risk: str = "LOW"
    dependency_risk: str = "LOW"

    license_detected: str = ""

    findings: list[str] = field(default_factory=list)
    recommended_action: str = ""
    error: Optional[str] = None
