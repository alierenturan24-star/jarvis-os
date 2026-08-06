from __future__ import annotations

from src.evaluation.models import RepoEvaluation
from src.integration.models import Conflict
from src.sandbox.models import SandboxResult

_SEVERITY_WEIGHT = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 4}
_PERMISSIVE_LICENSE_KEYWORDS = ("mit", "apache", "bsd", "isc", "mpl")


def estimate_risk(
    evaluation: RepoEvaluation,
    sandbox_result: SandboxResult,
    conflicts: list[Conflict],
) -> str:
    """LOW / MEDIUM / HIGH / CRITICAL.

    Puanlama: Evaluation Engine'in risk_level'ı (0-3), sandbox'ın
    network/execution/dependency risk kategorileri (0-2 her biri),
    belirsiz lisans (+3) ve her çakışmanın kendi ağırlığı toplanır.
    Eşikler: ≥8 CRITICAL, ≥5 HIGH, ≥2 MEDIUM, aksi LOW.
    """

    score = 0.0

    if evaluation.risk_level == "HIGH":
        score += 3
    elif evaluation.risk_level == "MEDIUM":
        score += 1

    if sandbox_result.network_risk == "HIGH":
        score += 2
    if sandbox_result.execution_risk == "HIGH":
        score += 2
    if sandbox_result.dependency_risk == "HIGH":
        score += 1

    if not sandbox_result.license_detected.strip():
        score += 3

    score += sum(_SEVERITY_WEIGHT.get(c.severity, 1) for c in conflicts)

    if score >= 8:
        return "CRITICAL"
    if score >= 5:
        return "HIGH"
    if score >= 2:
        return "MEDIUM"
    return "LOW"


def breaking_change_probability(conflicts: list[Conflict], target_module_exists: bool) -> float:
    """0-100 arası yüzde. Hedef modül zaten VARSA (mevcut kodu
    etkileyecek) taban çok daha yüksektir; isim çakışmaları ve
    provider/tool çakışmaları puanı daha da artırır."""

    base = 55.0 if target_module_exists else 10.0
    base += 15.0 * sum(1 for c in conflicts if c.type in ("same_class_name", "same_module_name", "duplicate_functionality"))
    base += 10.0 * sum(1 for c in conflicts if c.type in ("provider_conflict", "tool_conflict"))
    return round(min(100.0, base), 1)


def is_merge_ready(
    evaluation: RepoEvaluation,
    sandbox_result: SandboxResult,
    conflicts: list[Conflict],
    estimated_risk: str,
) -> bool:
    """``merge_ready=True`` YALNIZCA: uygun (izinli) lisans + düşük risk +
    duplicate yok + dependency çakışması yok + suitable_for_jarvis=True."""

    if not evaluation.suitable_for_jarvis:
        return False
    if estimated_risk != "LOW":
        return False

    license_text = sandbox_result.license_detected.strip().lower()
    if not license_text or not any(keyword in license_text for keyword in _PERMISSIVE_LICENSE_KEYWORDS):
        return False

    if any(c.type == "duplicate_functionality" for c in conflicts):
        return False
    if any(c.type == "dependency_conflict" for c in conflicts):
        return False

    return True
