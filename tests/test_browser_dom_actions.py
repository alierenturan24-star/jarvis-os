from __future__ import annotations

import unittest

from src.agents.browser_agent import BrowserAgent
from src.planner.task import Task
from src.tools.browser.dom_engine import InvalidDomIndexError
from src.tools.browser.playwright_session import PlaywrightSession
from src.tools.browser_tool import BrowserTool


class FakeLocator:
    def __init__(self, tag: str, attrs: dict | None = None, text: str = "") -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.text = text
        self.clicked = False

    def is_visible(self) -> bool:
        return True

    def get_attribute(self, name: str):
        return self.attrs.get(name)

    def inner_text(self) -> str:
        return self.text

    def evaluate(self, expression: str) -> str:
        return self.tag.upper()

    def click(self) -> None:
        self.clicked = True


class _FakeLocatorGroup:
    def __init__(self, locators: list[FakeLocator]) -> None:
        self._locators = locators

    def all(self) -> list[FakeLocator]:
        return list(self._locators)


class FakeBrowserPage:
    def __init__(self, locators: list[FakeLocator]) -> None:
        self.url = "about:blank"
        self._locators = locators

    def goto(self, url: str) -> None:
        self.url = url

    def title(self) -> str:
        return "Fake Page"

    def inner_text(self, _selector: str) -> str:
        return ""

    def locator(self, _selector: str) -> _FakeLocatorGroup:
        return _FakeLocatorGroup(self._locators)

    def click(self, _selector: str) -> None:
        pass

    def close(self) -> None:
        pass


class FakeBrowser:
    """``browser_launcher`` enjeksiyon noktasına verilen sahte tarayıcı.

    Playwright kurulu olmadan ``PlaywrightSession``'ın GERÇEK kodunu uçtan
    uca test etmeyi sağlar (bkz. ``PlaywrightSession`` docstring'i).
    """

    def __init__(self, locators: list[FakeLocator]) -> None:
        self._locators = locators
        self.pages: list[FakeBrowserPage] = []

    def new_page(self) -> FakeBrowserPage:
        page = FakeBrowserPage(self._locators)
        self.pages.append(page)
        return page

    def close(self) -> None:
        pass


def _make_session() -> tuple[PlaywrightSession, list[FakeLocator]]:
    locators = [
        FakeLocator("button", text="Gönder"),
        FakeLocator("a", attrs={"aria-label": "Ana sayfa", "href": "/"}),
    ]
    browser = FakeBrowser(locators)
    session = PlaywrightSession(browser_launcher=lambda: browser)
    return session, locators


class PlaywrightSessionDomTests(unittest.TestCase):
    def test_click_index_without_list_elements_raises(self):
        session, _ = _make_session()
        with self.assertRaises(InvalidDomIndexError):
            session.click_index(1)

    def test_list_elements_then_click_index_clicks_correct_element(self):
        session, locators = _make_session()

        rendered = session.list_elements()
        self.assertIn("[1] <button> Gönder", rendered)
        self.assertIn("[2] <link> Ana sayfa", rendered)

        session.click_index(1)
        self.assertTrue(locators[0].clicked)
        self.assertFalse(locators[1].clicked)

    def test_click_index_invalidates_snapshot_after_use(self):
        session, _ = _make_session()
        session.list_elements()
        session.click_index(1)

        with self.assertRaises(InvalidDomIndexError):
            session.click_index(2)

    def test_goto_invalidates_previous_snapshot(self):
        session, _ = _make_session()
        session.list_elements()
        session.goto("https://example.com")

        with self.assertRaises(InvalidDomIndexError):
            session.click_index(1)

    def test_click_index_with_out_of_range_index_raises(self):
        session, _ = _make_session()
        session.list_elements()

        with self.assertRaises(InvalidDomIndexError):
            session.click_index(999)


class BrowserToolDomActionTests(unittest.TestCase):
    def test_list_elements_action_returns_rendered_snapshot(self):
        session, _ = _make_session()
        tool = BrowserTool(session=session)

        result = tool.execute(action="list_elements")
        self.assertIn("[1] <button> Gönder", result)

    def test_click_index_action_missing_index_returns_friendly_message(self):
        session, _ = _make_session()
        tool = BrowserTool(session=session)

        result = tool.execute(action="click_index")
        self.assertEqual(result, "Element index'i ('index') belirtilmedi.")

    def test_click_index_action_invalid_index_returns_error_string(self):
        session, _ = _make_session()
        tool = BrowserTool(session=session)

        tool.execute(action="list_elements")
        result = tool.execute(action="click_index", index=999)

        self.assertTrue(result.startswith("Hata:"))

    def test_click_index_action_clicks_element(self):
        session, locators = _make_session()
        tool = BrowserTool(session=session)

        tool.execute(action="list_elements")
        result = tool.execute(action="click_index", index=1)

        self.assertTrue(locators[0].clicked)
        self.assertIn("Tıklandı [1]", result)


class BrowserAgentDomActionTests(unittest.TestCase):
    def _agent_with_fake_session(self) -> tuple[BrowserAgent, list[FakeLocator]]:
        session, locators = _make_session()
        agent = BrowserAgent()
        agent.browser = BrowserTool(session=session)
        return agent, locators

    def test_supports_new_actions(self):
        agent = BrowserAgent()
        self.assertTrue(agent.supports(Task(agent="browser", action="list_elements")))
        self.assertTrue(agent.supports(Task(agent="browser", action="click_index")))

    def test_execute_list_elements(self):
        agent, _ = self._agent_with_fake_session()
        result = agent.execute(Task(agent="browser", action="list_elements"))
        self.assertIn("[1] <button> Gönder", result)

    def test_execute_click_index_reads_index_from_metadata(self):
        agent, locators = self._agent_with_fake_session()
        agent.execute(Task(agent="browser", action="list_elements"))

        result = agent.execute(
            Task(agent="browser", action="click_index", metadata={"index": 1})
        )

        self.assertTrue(locators[0].clicked)
        self.assertIn("Tıklandı [1]", result)


if __name__ == "__main__":
    unittest.main()
