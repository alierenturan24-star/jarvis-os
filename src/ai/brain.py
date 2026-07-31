from src.memory.memory_manager import MemoryManager


class Brain:
    def __init__(self):
        self.memory = MemoryManager()

    # -----------------------------
    # Memory
    # -----------------------------

    def remember(self, key: str, value):
        self.memory.save(key, value)

    def recall(self, key: str):
        return self.memory.load(key)

    # -----------------------------
    # Future
    # -----------------------------

    def think(self, message: str):
        """
        Gelecekte burada;

        - Planlama
        - Karar verme
        - Araştırma
        - Tool seçimi
        - Agent yönetimi

        yapılacak.
        """

        return None