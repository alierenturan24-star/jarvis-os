import unittest

from src.registry.worker_registry import WorkerRegistry


class DummyWorker:
    def __init__(self, result: str = "ok") -> None:
        self.result = result

    def execute(self, task):
        return self.result


class WorkerRegistryTests(unittest.TestCase):
    def test_register_and_get_by_name(self):
        registry = WorkerRegistry()
        worker = DummyWorker()
        registry.register("research", worker, capabilities={"research"})
        self.assertIs(registry.get("research"), worker)

    def test_get_by_alias(self):
        registry = WorkerRegistry()
        worker = DummyWorker()
        registry.register("finance", worker, aliases={"finans"})
        self.assertIs(registry.get("finans"), worker)

    def test_best_worker_uses_priority(self):
        registry = WorkerRegistry()
        slow = DummyWorker("slow")
        fast = DummyWorker("fast")
        registry.register("slow", slow, capabilities={"analysis"}, priority=10)
        registry.register("fast", fast, capabilities={"analysis"}, priority=90)
        self.assertIs(registry.best("analysis"), fast)

    def test_duplicate_registration_is_rejected(self):
        registry = WorkerRegistry()
        registry.register("chat", DummyWorker())
        with self.assertRaises(ValueError):
            registry.register("chat", DummyWorker())

    def test_unregister_removes_aliases(self):
        registry = WorkerRegistry()
        registry.register("coding", DummyWorker(), aliases={"code"})
        self.assertTrue(registry.unregister("coding"))
        self.assertIsNone(registry.get("coding"))
        self.assertIsNone(registry.get("code"))


if __name__ == "__main__":
    unittest.main()
