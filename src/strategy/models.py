from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskCategory(str, Enum):
    """Sprint 34: AI Strategy Engine'in "Soru 1"e verdiği cevap.

    ``src.mission.models.MissionType`` İLE AYNI ŞEY DEĞİL ve onun yerine
    GEÇMEZ -- Department seçimi hâlâ tamamen ``classify_mission_type``/
    ``DepartmentOrchestrator.select_departments``'a aittir (bkz.
    ``strategy_engine.py``, bunları DOĞRUDAN çağırır). Bu enum yalnızca
    AI/Tool planlaması için kullanılan, PDF/VISION gibi Mission
    sisteminde (henüz) hiçbir karşılığı olmayan iki ek sinyali de
    kapsayan, daha zengin bir sınıflandırmadır.
    """

    RESEARCH = "research"
    CODE = "code"
    FINANCE = "finance"
    YOUTUBE = "youtube"
    BROWSER = "browser"
    GITHUB = "github"
    PDF = "pdf"
    VISION = "vision"
    OTHER = "other"


# AI seçiminde öncelik sırası (Sprint 34 HEDEF'inde istenen 5 katman).
TIER_LOCAL_FREE = "1-yerel-ücretsiz"
TIER_OPEN_SOURCE = "2-açık-kaynak"
TIER_FREE_SERVICE = "3-ücretsiz-servis"
TIER_CLOUD = "4-bulut"
TIER_PAID = "5-ücretli"

TIER_PRIORITY = (
    TIER_LOCAL_FREE,
    TIER_OPEN_SOURCE,
    TIER_FREE_SERVICE,
    TIER_CLOUD,
    TIER_PAID,
)


@dataclass(frozen=True)
class DepartmentChoice:
    """Bir departmanın bu görev için neden gerekli/gereksiz olduğu."""

    name: str
    reason: str


@dataclass(frozen=True)
class ToolChoice:
    """Bir Tool/modülün bu görev için neden gerekli olduğu (ya da henüz
    JARVIS'te karşılığı olmadığının dürüst itirafı -- bkz.
    ``strategy_engine._TOOLS_FOR_DEPARTMENT``)."""

    name: str
    reason: str


@dataclass(frozen=True)
class AIChoice:
    """Seçilen sağlayıcı + katman + gerekçe.

    ``src.providers.cost_optimizer.CostOptimizer.decide_for_message()``'in
    ZATEN ürettiği ``ModelDecision``'dan türetilir -- yeni bir maliyet/
    kalite puanlama sistemi İCAT EDİLMEZ, yalnızca 5 katmanlı (bkz.
    ``TIER_PRIORITY``) bir etikete eşlenir.
    """

    provider: str
    model: str
    tier: str
    reason: str
    estimated_cost: float
    confidence: int
    fallback_provider: str | None = None


@dataclass(frozen=True)
class AIStrategyPlan:
    """AI Strategy Engine'in bir görev için ürettiği TAM plan.

    Hiçbir alan bir görevi ÇALIŞTIRMAZ (bkz. Sprint 34 KURAL) -- yalnızca
    "hangi AI/Tool/Department, hangi sırayla ve NEDEN" sorularının
    (Sprint 34 HEDEF, soru 1-7) cevaplarını taşır.
    """

    request: str
    category: TaskCategory
    category_reason: str
    departments: tuple[DepartmentChoice, ...]
    tools: tuple[ToolChoice, ...]
    ai_choice: AIChoice
    free_sufficient: bool
    free_sufficient_reason: str
    local_sufficient: bool
    local_sufficient_reason: str
    paid_required: bool
    paid_required_reason: str
    # Sprint 40: "tek mission = tek provider" kısıtını kaldırmak için EK
    # (mevcut ``ai_choice`` alanı DEĞİŞMEDEN, geriye dönük uyumlu) bir
    # alan -- her LLM çağıran departman için AYRI hesaplanmış bir
    # ``AIChoice`` haritası (bkz. ``strategy_engine._TASK_TYPE_FOR_DEPARTMENT``).
    # Yeni bir karar mantığı İCAT ETMEZ -- ``CostOptimizer.decide()`` (ZATEN
    # VAR) departman başına AYRI çağrılır. LLM gerektirmeyen departmanlar
    # (github/browser/evaluation/sandbox/integration/automation/ai_discovery)
    # için hiç girdi YOKTUR -- boş sözlük varsayılanı geriye dönük
    # uyumluluğu (eski testler/çağıranlar) BOZMAZ.
    department_ai_choices: dict[str, AIChoice] = field(default_factory=dict)


@dataclass(frozen=True)
class SelfImprovementReview:
    """Sprint 34 SELF IMPROVEMENT: bir görev sonrası (veya bir plan
    üzerinden, mission henüz çalışmadıysa) değerlendirme. Hiçbir yeni
    ölçüm İCAT ETMEZ -- yalnızca zaten hesaplanmış sinyallere (CostOptimizer'ın
    kendi görev profili tablosu, varsa AI Discovery department sonucu)
    dayanır."""

    cheaper_ai_possible: bool
    cheaper_ai_note: str
    faster_ai_possible: bool
    faster_ai_note: str
    quality_risk: bool
    quality_risk_note: str
    new_free_model_available: bool
    new_free_model_note: str
