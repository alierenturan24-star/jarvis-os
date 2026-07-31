import json
import os


class MemoryManager:
    def __init__(self):
        self.memory_file = "memory.json"

        if not os.path.exists(self.memory_file):
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

    def _load_memory(self):
        with open(self.memory_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_memory(self, data):
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def save(self, key, value):
        data = self._load_memory()
        data[key] = value
        self._save_memory(data)

    def load(self, key):
        data = self._load_memory()
        return data.get(key)

    def all(self):
        return self._load_memory()

    def delete(self, key):
        data = self._load_memory()

        if key in data:
            del data[key]
            self._save_memory(data)

    def clear(self):
        self._save_memory({})