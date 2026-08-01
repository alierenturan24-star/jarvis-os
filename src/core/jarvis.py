from src.ai.brain import Brain
from src.core.commander import Commander

from src.reasoning.reasoning_engine import ReasoningEngine

from src.planner.planner import Planner
from src.planner.task_queue import TaskQueue

from src.core.agent_router import AgentRouter
from src.core.executor import Executor


class Jarvis:

    def __init__(self):

        self.brain = Brain()

        self.commander = Commander()

        self.reasoning = ReasoningEngine()

        self.planner = Planner()

        self.queue = TaskQueue()

        self.agent_router = AgentRouter()

        self.executor = Executor(
            self.queue,
            self.agent_router,
        )

    def chat(self, message: str):

        # 1) Görevi analiz et
        plan = self.reasoning.analyze(message)

        # 2) Görev listesini oluştur
        tasks = self.planner.build(message)

        # 3) Kuyruğa ekle
        self.queue.clear()

        for task in tasks:
            self.queue.add(task)

        # 4) Görevleri çalıştır
        results = self.executor.run()

        # 5) Eğer görev üretildiyse onları döndür
        if results:
            return "\n".join(results)

        # 6) Hiç görev oluşmadıysa normal sohbet
        return self.commander.process(message)

    def remember(self, key, value):

        self.brain.remember(key, value)

    def recall(self, key):

        return self.brain.recall(key)