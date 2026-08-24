from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from src.tools.browser.playwright_session import PlaywrightSession


class ThreadRecordingLocator:
    def __init__(self, tag: str = "button", text: str = "Tikla") -> None:
        self.tag = tag
        self.text = text
        self.clicked_thread_id: int | None = None

    def is_visible(self) -> bool:
        return True

    def get_attribute(self, _name: str):
        return None

    def inner_text(self) -> str:
        return self.text

    def evaluate(self, _expression: str) -> str:
        return self.tag.upper()

    def click(self) -> None:
        self.clicked_thread_id = threading.get_ident()


class ThreadRecordingLocatorGroup:
    def __init__(self, locators: list[ThreadRecordingLocator]) -> None:
        self._locators = locators

    def all(self) -> list[ThreadRecordingLocator]:
        return list(self._locators)


class ThreadRecordingPage:
    """Sahte Playwright ``Page``'i: her gerçek işlemin hangi OS thread'inde
    çalıştığını kaydeder (üretim kodu değiştirilmeden, yalnızca testte)."""

    def __init__(self, locators: list[ThreadRecordingLocator]) -> None:
        self.url = "about:blank"
        self._locators = locators
        self.goto_thread_id: int | None = None
        self.locator_thread_id: int | None = None

    def goto(self, url: str) -> None:
        self.goto_thread_id = threading.get_ident()
        self.url = url

    def title(self) -> str:
        return "Fake Page"

    def inner_text(self, _selector: str) -> str:
        return ""

    def locator(self, _selector: str) -> ThreadRecordingLocatorGroup:
        self.locator_thread_id = threading.get_ident()
        return ThreadRecordingLocatorGroup(self._locators)

    def click(self, _selector: str) -> None:
        pass

    def close(self) -> None:
        pass


class ThreadRecordingBrowser:
    def __init__(self, locators: list[ThreadRecordingLocator]) -> None:
        self._locators = locators
        self.new_page_thread_id: int | None = None
        self.pages: list[ThreadRecordingPage] = []

    def new_page(self) -> ThreadRecordingPage:
        self.new_page_thread_id = threading.get_ident()
        page = ThreadRecordingPage(self._locators)
        self.pages.append(page)
        return page

    def close(self) -> None:
        pass


def _call_from_new_thread(fn, *args, **kwargs):
    """``JobManager.run_task()``'ın her görev için taze, tek-worker'lı bir
    ``ThreadPoolExecutor`` oluşturmasını taklit ederek çağrıyı YENİ ve
    FARKLI bir dış thread'den yapar (bkz. Debug Sprint 30 kanıtı)."""

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(fn, *args, **kwargs).result()


class OwnerThreadAffinityTests(unittest.TestCase):
    def test_real_playwright_calls_always_land_on_the_same_owner_thread(self):
        locators = [ThreadRecordingLocator()]
        browser = ThreadRecordingBrowser(locators)
        session = PlaywrightSession(browser_launcher=lambda: browser)

        # "open": JobManager tarzı taze bir dış thread'den.
        _call_from_new_thread(session.goto, "https://example.com")
        # "list_elements": BAŞKA, farklı bir dış thread'den (Debug
        # Sprint 30'da gözlenen gerçek senaryo).
        _call_from_new_thread(session.list_elements)

        page = browser.pages[0]

        # Gerçek Playwright'a dokunan iki çağrı (goto ve locator) HER
        # ZAMAN aynı owner thread'e düşmeli -- dış çağıran thread'lerin
        # farklı olmasından TAMAMEN bağımsız olarak.
        self.assertIsNotNone(page.goto_thread_id)
        self.assertIsNotNone(page.locator_thread_id)
        self.assertEqual(page.goto_thread_id, page.locator_thread_id)

        # Owner thread, testin kendi thread'inden de FARKLI olmalı
        # (kendi kalıcı thread'ini gerçekten sahiplendiğini doğrular).
        self.assertNotEqual(page.goto_thread_id, threading.get_ident())

    def test_click_index_runs_on_same_owner_thread_as_list_elements(self):
        locator = ThreadRecordingLocator()
        browser = ThreadRecordingBrowser([locator])
        session = PlaywrightSession(browser_launcher=lambda: browser)

        _call_from_new_thread(session.goto, "https://example.com")
        _call_from_new_thread(session.list_elements)
        page = browser.pages[0]

        _call_from_new_thread(session.click_index, 1)

        self.assertEqual(locator.clicked_thread_id, page.locator_thread_id)

    def test_reentrant_call_from_owner_thread_does_not_deadlock(self):
        # browser_launcher'in KENDİSİ session.list_elements()'i çağırarak
        # owner thread içinden yeniden-giriş senaryosunu simüle eder.
        locators: list[ThreadRecordingLocator] = []
        holder: dict = {}

        def launcher():
            browser = ThreadRecordingBrowser(locators)
            holder["browser"] = browser
            return browser

        session = PlaywrightSession(browser_launcher=launcher)

        def start_then_list_elements():
            session.start()
            return session.list_elements()

        result = _call_from_new_thread(start_then_list_elements)

        self.assertEqual(result, "Sayfada etkileşimli eleman bulunamadı.")

    def test_exceptions_raised_on_owner_thread_propagate_to_caller(self):
        session = PlaywrightSession(browser_launcher=lambda: ThreadRecordingBrowser([]))

        with self.assertRaises(ValueError):
            _call_from_new_thread(session.goto, "")


class StopCleansUpOwnerThreadTests(unittest.TestCase):
    def test_stop_shuts_down_owner_thread_without_leaking(self):
        session = PlaywrightSession(browser_launcher=lambda: ThreadRecordingBrowser([]))

        before = {t.ident for t in threading.enumerate()}
        session.start()
        during = {t.ident for t in threading.enumerate()}
        self.assertTrue(during - before, "start() bir owner thread oluşturmuş olmalı.")

        session.stop()

        after = {t.ident for t in threading.enumerate()}
        self.assertEqual(after - before, set(), "stop() sonrası thread sızıntısı olmamalı.")
        self.assertIsNone(session._owner_executor)

    def test_stop_is_idempotent_and_safe_when_never_started(self):
        session = PlaywrightSession(browser_launcher=lambda: ThreadRecordingBrowser([]))

        session.stop()
        session.stop()


if __name__ == "__main__":
    unittest.main()
