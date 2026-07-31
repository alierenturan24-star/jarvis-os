import json
import os


class MemoryManager:
    def __init__(self):
        base_dir = os.path.dirname(__file__)
        self.file = os.path.join(base_dir, "memory.json")

        if not os.path.exists(self.file):
            with open(self.file, "w", encoding="utf-8") as f:
                json.dump({}, f)