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

        action = kwargs.get("action")
        url = kwargs.get("url")

        if action == "open":

            if not url.startswith("http"):

                url = "https://" + url

            webbrowser.open(url)

            return f"Açıldı: {url}"

        return "Geçersiz işlem."