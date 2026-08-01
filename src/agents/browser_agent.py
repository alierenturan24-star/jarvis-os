from src.tools.browser_tool import BrowserTool


class BrowserAgent:

    def __init__(self):
        self.browser = BrowserTool()

    def execute(self, command: str):

        text = command.lower()

        if "google" in text:
            return self.browser.execute(
                action="open",
                url="https://www.google.com"
            )

        if "youtube" in text:
            return self.browser.execute(
                action="open",
                url="https://www.youtube.com"
            )

        if "chatgpt" in text:
            return self.browser.execute(
                action="open",
                url="https://chat.openai.com"
            )

        if "github" in text:
            return self.browser.execute(
                action="open",
                url="https://github.com"
            )

        return "Açılacak site bulunamadı."