from src.agents.base_agent import BaseAgent
from src.finance.manager import FinanceManager
from src.planner.task import Task
from src.utils.text_cleaner import clean_finance_asset


_STRATEGY_GOAL_CUES = ("stratej", "strategy", "backtest", "out-of-sample", "oos", "overfitting", "paper")


class FinanceAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("Finance Agent")
        self.manager = FinanceManager()

    @staticmethod
    def _clean_asset(message: str) -> str:
        return clean_finance_asset(message)

    def supports(self, task) -> bool:
        return bool(self._clean_asset(str(getattr(task, "target", ""))))

    def execute(self, task: Task) -> str:
        message = str(getattr(task, "target", ""))
        lowered = message.casefold()
        if any(cue in lowered for cue in _STRATEGY_GOAL_CUES):
            from src.control_center.finance_engine import FinancePaperEngine
            from src.control_center.store import ControlCenterStore
            import re

            match = re.search(r"\b(BTC|BITCOIN|ETH|ETHEREUM|[A-Z]{2,10}(?:USDT|USD|EUR))\b", message, re.I)
            asset = match.group(1) if match else "BTC"
            engine = FinancePaperEngine(ControlCenterStore())
            wants_novel = any(cue in lowered for cue in (
                "yeni stratej", "new strateg", "novel", "exploration", "keşfet", "kesfet",
                "bounded", "yeni gÃ¼venli", "keÅŸfet",
            ))
            lab = engine.explore_strategies(asset) if wants_novel else engine.strategy_lab(asset)
            task.metadata["report"] = {
                "strategy_lab": lab,
                "market_data": {"source": lab["source"], "market_truth_source": True},
                "repository_role": "tool capability only; not market truth",
                "live_activation": False,
            }
            return (
                f"Strategy Lab tamamlandı: {lab['strategy_count']} aday aynı veri ve maliyetlerle test edildi.\n"
                f"Karar: {lab['decision']}\nEn iyi aday: {lab['best_candidate'] or '-'}\n"
                "Gerçek para kullanılmadı; LIVE execution devre dışı."
            )
        asset = self._clean_asset(message)

        if not asset:
            return "Analiz edilecek coin, hisse veya varlığı yaz."

        # Sprint 35: AI Strategy Engine'in seçtiği provider'ı (varsa) mevcut
        # FinanceManager/ProviderManager zincirine iletir.
        preferred_provider = getattr(task, "metadata", {}).get("preferred_ai_provider")

        return self.manager.analyze(asset, preferred_provider=preferred_provider)
