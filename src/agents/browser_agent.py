from __future__ import annotations

from src.agents.base_agent import BaseAgent
from src.planner.task import Task
from src.tools.browser_tool import BrowserTool


class BrowserAgent(BaseAgent):
    """Playwright tabanlı BrowserTool'u kullanan tarayıcı otomasyon ajanı."""

    # Geriye dönük uyumlu kısayollar: task.action -> sabit URL.
    SHORTCUT_URLS = {
        "open_google": "https://www.google.com",
        "open_youtube": "https://www.youtube.com",
        "open_github": "https://github.com",
        "open_chatgpt": "https://chatgpt.com",
    }

    # BrowserTool'a doğrudan eşlenen, ek veri gerektiren eylemler.
    TOOL_ACTIONS = {
        "open",
        "open_url",
        "search",
        "new_tab",
        "switch_tab",
        "close_tab",
        "list_tabs",
        "read_page",
        "click",
        "download",
        "screenshot",
        "close",
        "list_elements",
        "click_index",
    }

    def __init__(self) -> None:
        super().__init__("Browser Agent")
        self.browser = BrowserTool()

    def supports(self, task) -> bool:
        action = getattr(task, "action", None)
        return action in self.SHORTCUT_URLS or action in self.TOOL_ACTIONS

    def health(self) -> dict:
        info = self.browser.get_info()
        return {
            "agent": self.name,
            "available": info.get("playwright_available", False),
            "playwright_available": info.get("playwright_available", False),
        }

    def execute(self, task: Task) -> str:
        action = task.action
        metadata = getattr(task, "metadata", None) or {}

        if action in self.SHORTCUT_URLS:
            return str(
                self.browser.execute(
                    action="open",
                    url=self.SHORTCUT_URLS[action],
                )
            )

        if action in ("open", "open_url"):
            url = metadata.get("url") or task.target
            return str(self.browser.execute(action="open", url=url))

        if action == "search":
            query = metadata.get("query") or task.target
            engine = metadata.get("engine", "google")
            return str(
                self.browser.execute(action="search", query=query, engine=engine)
            )

        if action == "new_tab":
            return str(self.browser.execute(action="new_tab"))

        if action == "switch_tab":
            return str(
                self.browser.execute(action="switch_tab", index=metadata.get("index"))
            )

        if action == "close_tab":
            return str(
                self.browser.execute(action="close_tab", index=metadata.get("index"))
            )

        if action == "list_tabs":
            return str(self.browser.execute(action="list_tabs"))

        if action == "read_page":
            return str(self.browser.execute(action="read_page"))

        if action == "click":
            selector = metadata.get("selector") or task.target
            return str(self.browser.execute(action="click", selector=selector))

        if action == "download":
            return str(
                self.browser.execute(
                    action="download",
                    selector=metadata.get("selector"),
                    save_path=metadata.get("save_path"),
                )
            )

        if action == "screenshot":
            save_path = metadata.get("save_path") or task.target
            return str(self.browser.execute(action="screenshot", save_path=save_path))

        if action == "list_elements":
            return str(self.browser.execute(action="list_elements"))

        if action == "click_index":
            index = metadata.get("index")
            if index is None:
                index = task.target
            return str(self.browser.execute(action="click_index", index=index))

        if action == "close":
            return str(self.browser.execute(action="close"))

        return "Açılacak site veya desteklenen bir tarayıcı işlemi bulunamadı."
