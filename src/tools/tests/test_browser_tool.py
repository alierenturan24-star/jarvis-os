from __future__ import annotations

from src.tools.browser_tool import BrowserTool

# Mission repair (real Swiss-Insider-Shorts follow-up evidence, item 6): a
# real mission's browser search landed on a Google anti-bot interstitial
# ("/sorry/...") and it was accepted as if it were normal search-result
# evidence. Uses a fake, duck-typed session (no real Playwright/network) --
# no live browsing.


class _FakeSession:
    def __init__(self, *, search_url="https://example.com/results", page=None):
        self._search_url = search_url
        self._page = page or {"url": "https://example.com/results", "title": "Results", "text": "some content"}

    def search(self, query, engine="google"):
        return self._search_url

    def goto(self, url):
        return self._search_url

    def read_page(self):
        return self._page


class TestGoogleAntiBotSearchDetection:
    def test_sorry_url_is_reported_as_a_failure_not_a_result(self):
        tool = BrowserTool(session=_FakeSession(
            search_url="https://www.google.com/sorry/index?continue=https://www.google.com/search%3Fq%3Dtest",
        ))
        output = tool.execute(action="search", query="test", engine="google")
        assert output.casefold().startswith("hata")

    def test_normal_search_result_is_unaffected(self):
        tool = BrowserTool(session=_FakeSession(
            search_url="https://www.google.com/search?q=test",
        ))
        output = tool.execute(action="search", query="test", engine="google")
        assert not output.casefold().startswith("hata")
        assert "Arama yapıldı" in output

    def test_open_action_also_detects_anti_bot_redirect(self):
        tool = BrowserTool(session=_FakeSession(
            search_url="https://www.google.com/sorry/index",
        ))
        output = tool.execute(action="open", url="https://www.google.com/search?q=test")
        assert output.casefold().startswith("hata")


class TestGoogleAntiBotPageContentDetection:
    def test_captcha_text_marker_is_reported_as_a_failure(self):
        tool = BrowserTool(session=_FakeSession(page={
            "url": "https://www.google.com/sorry/index",
            "title": "About this page",
            "text": "Our systems have detected unusual traffic from your computer network.",
        }))
        output = tool.execute(action="read_page")
        assert output.casefold().startswith("hata")

    def test_normal_page_content_is_unaffected(self):
        tool = BrowserTool(session=_FakeSession(page={
            "url": "https://example.com/article",
            "title": "A real article",
            "text": "This is genuine page content about a real topic.",
        }))
        output = tool.execute(action="read_page")
        assert not output.casefold().startswith("hata")
        assert "A real article" in output
