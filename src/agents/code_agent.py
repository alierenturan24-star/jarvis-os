from src.agents.base_agent import BaseAgent


class CodeAgent(BaseAgent):

    def __init__(self):
        super().__init__("Code Agent")

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