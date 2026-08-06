from __future__ import annotations

from src.providers.cost_optimizer import CostOptimizer, ModelDecision
from src.providers.provider_manager import ProviderManager


class CouncilCostAdvisor:
    """AI Konseyi için maliyet-farkında model seçimi/raporlaması sağlar.

    Mevcut ``AICouncil.ask()`` akışını (ve dolayısıyla konsey davranışını)
    değiştirmez; ``CostOptimizer`` üzerinden ``ProviderManager`` ile uyumlu
    çalışan ek bir öneri/raporlama katmanıdır.
    """

    def __init__(self, provider_manager: ProviderManager | None = None) -> None:
        self.optimizer = CostOptimizer(provider_manager)

    def advise(self, message: str) -> ModelDecision:
        """Verilen mesaj için en düşük maliyetli ama yeterli model kararını döndürür."""
        return self.optimizer.decide_for_message(message)

    def explain(self, message: str) -> str:
        """``advise`` sonucunu okunabilir bir rapor metnine çevirir."""
        return self.optimizer.report(self.advise(message))
