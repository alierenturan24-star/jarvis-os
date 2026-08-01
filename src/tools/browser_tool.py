import webbrowser
from src.tools.base_tool import BaseTool


class BrowserTool(BaseTool):

    def __init__(self):
        super().__init__(
            name="Browser Tool",
            description="Tarayıcı işlemleri",
            requires_confirmation=False,
        )

    def execute(self, **kwargs):

        action = kwargs.get("action", "open")
        url = kwargs.get("url")

        if action == "open":
            return self.open(url)

        return "Geçersiz işlem."

    def open(self, url):

        if not url:
            return "URL belirtilmedi."

        try:
            webbrowser.open(url)
            return "Tarayıcı açıldı."

        except Exception as e:
            return f"Hata: {e}"

    def get_info(self):
        return {
            "name": self.name,
            "description": self.description,
        }