from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RepoEvaluation:
    """Bir GitHub reposunun, JARVIS'e olası entegrasyon ÖNCESİNDE yapılan
    çok kriterli değerlendirmesinin sonucu.

    ``EvaluationEngine.evaluate()`` bu tipi üretir. Girdi olarak
    ``src.github.models.RepoData`` alır (``GitHubIntelligence.search()``
    çıktısı); hiçbir repoyu klonlamaz/indirmez — yalnızca GitHub API'den
    zaten toplanmış meta veriye dayanır.
    """

    name: str
    url: str

    overall_score: float
    architecture_score: float
    activity_score: float
    community_score: float
    license_score: float
    security_score: float
    compatibility_score: float
    maintenance_score: float
    relevance_score: float

    recommendation: str

    # "Bu repo gerçekten Jarvis'e uygun mu?"
    suitable_for_jarvis: bool
    # "Mevcut mimarimizde hangi modülü geliştirir?"
    target_module: str
    # "Tahmini entegrasyon zorluğu nedir?"
    integration_difficulty: str
    # "Risk seviyesi nedir?" — LOW / MEDIUM / HIGH
    risk_level: str
