from dataclasses import dataclass, field

# Geriye dönük uyumluluk / kolay erişim: ``ModelDecision`` asıl olarak
# ``src.providers.cost_optimizer`` içinde tanımlıdır (CostOptimizer,
# ProviderManager ile birlikte çalışır); burada da erişilebilir kılınır.
from src.providers.cost_optimizer import ModelDecision  # noqa: F401


@dataclass
class ModelProfile:
    name: str
    provider: str
    model: str
    strengths: list[str] = field(default_factory=list)
    enabled: bool = True
    local: bool = False
    cost_score: int = 50
    speed_score: int = 50
    quality_score: int = 50
    # Model öncelik sistemi: görev tipleri arası genel tercih ağırlığı
    # (yüksek = daha öncelikli). Görev tipine özel sıralama
    # CouncilRegistry.TASK_PROVIDER_MAP üzerinden yönetilir; bu alan
    # fallback sıralaması ve consensus ağırlıklandırması için kullanılır.
    priority: int = 50


@dataclass
class CouncilResponse:
    model_name: str
    provider: str
    answer: str
    success: bool
    confidence: int
    error: str = ""
    # Consensus altyapısının öncelik-ağırlıklı güven hesaplaması için taşınır.
    priority: int = 50


@dataclass
class CouncilDecision:
    final_answer: str
    confidence: int
    agreement: int
    responses: list[CouncilResponse]
    # Hangi görev tipi tespit edilerek seçim yapıldığı (coding/research/finance/general).
    task_type: str = ""
