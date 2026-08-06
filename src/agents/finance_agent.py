from src.agents.base_agent import BaseAgent
from src.finance.manager import FinanceManager
from src.planner.task import Task
from src.utils.text_cleaner import clean_finance_asset


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
        asset = self._clean_asset(message)

        if not asset:
            return "Analiz edilecek coin, hisse veya varlığı yaz."

        return self.manager.analyze(asset)
