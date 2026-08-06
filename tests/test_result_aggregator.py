import unittest

from src.core.result_aggregator import ResultAggregator
from src.planner.task import Task


class ResultAggregatorTests(unittest.TestCase):
    def test_multi_task_contains_executive_summary(self):
        tasks = [
            Task(agent="finance", action="analyze", target="Bitcoin"),
            Task(agent="research", action="research", target="NVIDIA"),
        ]
        result = ResultAggregator().aggregate(tasks, ["Tamamlandı", "Bu konu daha önce araştırılmış."])
        self.assertIn("JARVIS YÖNETİCİ ÖZETİ", result)
        self.assertIn("Tamamlanan görev: 2/2", result)
        self.assertIn("güncelle", result)
