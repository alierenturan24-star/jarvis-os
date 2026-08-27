from __future__ import annotations

import re
from typing import Any, Optional

from src.tools.base_tool import BaseTool
from src.tools.browser.playwright_session import (
    PlaywrightNotAvailable,
    PlaywrightSession,
)

# Mission repair (real Swiss-Insider-Shorts follow-up evidence, item 6): a
# real mission's browser search landed on a Google anti-bot interstitial
# ("/sorry/...") and it was accepted as if it were a normal search result --
# neither ``search()``/``goto()`` (bare URL) nor ``read_page()`` (bare
# title/text) checked for this. Generic (not Google-specific wording only --
# also covers the common "unusual traffic"/captcha phrasing other engines
# use) so a blocked page is reported as a FAILURE (``BaseAgent.verify()``
# already treats a "Hata:"-prefixed string as failed, see
# ``src.agents.base_agent``), never silently returned as usable evidence.
_ANTI_BOT_URL_PATTERN = re.compile(r"/sorry/|/sorry\b", re.IGNORECASE)
_ANTI_BOT_TEXT_MARKERS = (
    "unusual traffic", "our systems have detected unusual traffic",
    "captcha", "recaptcha", "isn't a robot", "i'm not a robot",
    "before you continue to google search",
)


def _anti_bot_block_reason(url: str, title: str = "", text: str = "") -> Optional[str]:
    """``None`` if nothing looks like an anti-bot interstitial; otherwise a
    short reason string suitable for a "Hata: ..." failure message."""

    lowered_url = (url or "").casefold()
    if _ANTI_BOT_URL_PATTERN.search(lowered_url):
        return f"anti-bot/doğrulama sayfasına yönlendirildi (URL: {url})"
    haystack = f"{title} {text}".casefold()
    for marker in _ANTI_BOT_TEXT_MARKERS:
        if marker in haystack:
            return f'anti-bot/doğrulama sayfası tespit edildi ("{marker}" ibaresi)'
    return None


class BrowserTool(BaseTool):
    """Playwright tabanlı gerçek tarayıcı otomasyon aracı.

    ``execute(action=..., **kwargs)`` sözleşmesi korunmuştur (ToolManager
    ve BrowserAgent bunu kullanır); desteklenen eylemler genişletilmiştir:
    open, search, new_tab, switch_tab, close_tab, list_tabs, read_page,
    click, download, screenshot, close, list_elements, click_index.
    """

    def __init__(self, session: Optional[PlaywrightSession] = None) -> None:
        super().__init__(
            name="Browser Tool",
            description=(
                "Playwright tabanlı tarayıcı otomasyonu: sekme yönetimi, "
                "gezinme, arama, sayfa okuma, tıklama, indirme, screenshot."
            ),
            requires_confirmation=False,
        )
        self.session = session or PlaywrightSession()

    def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "open")

        try:
            if action == "open":
                return self._open(kwargs.get("url"))
            if action == "search":
                return self._search(kwargs.get("query"), kwargs.get("engine", "google"))
            if action == "new_tab":
                return self._new_tab()
            if action == "switch_tab":
                return self._switch_tab(kwargs.get("index"))
            if action == "close_tab":
                return self._close_tab(kwargs.get("index"))
            if action == "list_tabs":
                return self._list_tabs()
            if action == "read_page":
                return self._read_page()
            if action == "click":
                return self._click(kwargs.get("selector"))
            if action == "download":
                return self._download(kwargs.get("selector"), kwargs.get("save_path"))
            if action == "screenshot":
                return self._screenshot(kwargs.get("save_path"))
            if action == "list_elements":
                return self._list_elements()
            if action == "click_index":
                return self._click_index(kwargs.get("index"))
            if action == "close":
                self.session.stop()
                return "Tarayıcı kapatıldı."

            return "Geçersiz işlem."

        except PlaywrightNotAvailable as error:
            return str(error)
        except Exception as error:
            return f"Hata: {error}"

    # --- Eylemler -----------------------------------------------------

    def _open(self, url) -> str:
        if not url:
            return "URL belirtilmedi."
        final_url = self.session.goto(url)
        block_reason = _anti_bot_block_reason(final_url)
        if block_reason:
            return f"Hata: sayfa açılamadı -- {block_reason}"
        return f"Sayfa açıldı: {final_url}"

    def _search(self, query, engine) -> str:
        if not query:
            return "Arama metni belirtilmedi."
        final_url = self.session.search(query, engine=engine)
        block_reason = _anti_bot_block_reason(final_url)
        if block_reason:
            return f"Hata: arama sonucu alınamadı -- {block_reason}"
        return f"Arama yapıldı: {final_url}"

    def _new_tab(self) -> str:
        index = self.session.new_tab()
        return f"Yeni sekme açıldı (index={index})."

    def _switch_tab(self, index) -> str:
        if index is None:
            return "Sekme index'i belirtilmedi."
        ok = self.session.switch_tab(int(index))
        return f"Sekme {index} aktif edildi." if ok else f"Sekme {index} bulunamadı."

    def _close_tab(self, index) -> str:
        target = None if index is None else int(index)
        ok = self.session.close_tab(target)
        return "Sekme kapatıldı." if ok else "Kapatılacak sekme bulunamadı."

    def _list_tabs(self) -> str:
        tabs = self.session.list_tabs()

        if not tabs:
            return "Açık sekme yok."

        lines = [
            f"[{tab['index']}]{' *' if tab['active'] else ''} "
            f"{tab['title'] or tab['url']}"
            for tab in tabs
        ]
        return "\n".join(lines)

    def _read_page(self) -> str:
        page = self.session.read_page()
        preview = page["text"].strip()[:2000]
        block_reason = _anti_bot_block_reason(page["url"], page["title"], preview)
        if block_reason:
            return (
                f"Hata: sayfa içeriği güvenilir araştırma kanıtı olarak kabul edilmedi -- {block_reason}"
                f"\nURL: {page['url']}"
            )
        return f"Başlık: {page['title']}\nURL: {page['url']}\n\n{preview}"

    def _click(self, selector) -> str:
        if not selector:
            return "Tıklanacak eleman belirtilmedi."
        self.session.click(selector)
        return f"Tıklandı: {selector}"

    def _download(self, selector, save_path) -> str:
        if not selector or not save_path:
            return "İndirme için 'selector' ve 'save_path' gerekli."
        path = self.session.download(selector, save_path)
        return f"Dosya indirildi: {path}"

    def _screenshot(self, save_path) -> str:
        if not save_path:
            return "Kayıt yolu ('save_path') belirtilmedi."
        path = self.session.screenshot(save_path)
        return f"Ekran görüntüsü kaydedildi: {path}"

    def _list_elements(self) -> str:
        return self.session.list_elements()

    def _click_index(self, index) -> str:
        if index is None:
            return "Element index'i ('index') belirtilmedi."
        clicked = self.session.click_index(int(index))
        return f"Tıklandı [{index}]: {clicked}"

    # --- Bilgi -----------------------------------------------------------

    def get_info(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "requires_confirmation": self.requires_confirmation,
            "playwright_available": self._playwright_installed(),
        }

    @staticmethod
    def _playwright_installed() -> bool:
        try:
            import playwright  # noqa: F401

            return True
        except ImportError:
            return False
