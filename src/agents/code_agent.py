from src.agents.base_agent import BaseAgent


class CodeAgent(BaseAgent):

    def __init__(self):
        super().__init__("Code Agent")

    def supports(self, task) -> bool:
        return self.can_handle(str(getattr(task, "target", "")))

    def execute(self, task) -> str:
        message = str(getattr(task, "target", ""))

        if not self.can_handle(message):
            return "Bu görev kodlama ajanının kapsamı dışında."

        return self.build_instruction()

    def can_handle(self, message: str) -> bool:

        keywords = [
            "python",
            "kod",
            "code",
            "program",
            "script",
            "class",
            "fonksiyon",
            "hata",
            "bug",
        ]

        text = message.lower()

        return any(word in text for word in keywords)

    def build_instruction(self) -> str:

        return """
Bu yazılım geliştirme görevidir.

Kod okunabilir olsun.

Açıklama yap.

Kullanıcı istemedikçe gereksiz kod üretme.
"""