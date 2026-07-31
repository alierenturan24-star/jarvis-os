from pathlib import Path

from src.tools.base_tool import BaseTool


class FolderTool(BaseTool):

    def __init__(self):

        super().__init__(
            name="Folder Tool",
            description="Klasör işlemleri",
            requires_confirmation=True,
        )

    def execute(self, **kwargs):

        action = kwargs.get("action")

        path = kwargs.get("path")

        if action == "create":
            return self.create(path)

        if action == "exists":
            return str(Path(path).exists())

        return "Geçersiz işlem."

    def create(self, path):

        try:

            Path(path).mkdir(
                parents=True,
                exist_ok=True,
            )

            return "Klasör oluşturuldu."

        except Exception as e:

            return f"Hata: {e}"