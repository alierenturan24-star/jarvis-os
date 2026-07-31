from pathlib import Path

from src.tools.base_tool import BaseTool


class FileTool(BaseTool):

    def __init__(self):
        super().__init__(
            name="File Tool",
            description="Dosya okuma ve yazma işlemleri",
            requires_confirmation=True,
        )

    def execute(self, **kwargs):

        action = kwargs.get("action")
        path = kwargs.get("path")
        content = kwargs.get("content", "")

        if action == "read":
            return self.read_file(path)

        if action == "write":
            return self.write_file(path, content)

        if action == "exists":
            return str(Path(path).exists())

        return "Geçersiz işlem."

    def read_file(self, path):

        try:
            return Path(path).read_text(encoding="utf-8")

        except Exception as e:
            return f"Hata: {e}"

    def write_file(self, path, content):

        try:
            Path(path).write_text(
                content,
                encoding="utf-8",
            )

            return "Dosya başarıyla kaydedildi."

        except Exception as e:
            return f"Hata: {e}"