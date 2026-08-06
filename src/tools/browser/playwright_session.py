from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote_plus


class PlaywrightNotAvailable(RuntimeError):
    """Playwright paketi ve/veya tarayıcı ikilileri kurulu değil."""


class PlaywrightSession:
    """Playwright tabanlı gerçek tarayıcı kontrol katmanı.

    Playwright, bu modül import edildiğinde DEĞİL, bir oturum gerçekten
    başlatılmaya çalışıldığında (``start()`` / ilk eylem) içe aktarılır.
    Böylece playwright kurulu olmasa bile proje sorunsuz import edilip
    çalıştırılabilir; yalnızca tarayıcı gerçekten kullanılmaya
    çalışıldığında anlaşılır bir hata verir.

    ``browser_launcher`` parametresi test/enjeksiyon amaçlıdır: playwright
    kurulu olmadan bu sınıfın tüm sekme/eylem mantığı sahte bir tarayıcı
    nesnesiyle doğrulanabilir.
    """

    SEARCH_ENGINES = {
        "google": "https://www.google.com/search?q={query}",
        "duckduckgo": "https://duckduckgo.com/?q={query}",
        "github": "https://github.com/search?q={query}",
        "youtube": "https://www.youtube.com/results?search_query={query}",
    }

    def __init__(
        self,
        headless: bool = True,
        browser_launcher: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.headless = headless
        self._browser_launcher = browser_launcher
        self._playwright = None
        self._browser = None
        self._pages: list[Any] = []
        self._active_index: int = -1

    # --- Yaşam döngüsü --------------------------------------------------

    @property
    def is_started(self) -> bool:
        return self._browser is not None

    def start(self) -> None:
        if self.is_started:
            return

        self._browser = (
            self._browser_launcher()
            if self._browser_launcher is not None
            else self._launch_real_chrome()
        )

        page = self._browser.new_page()
        self._pages = [page]
        self._active_index = 0

    def _launch_real_chrome(self) -> Any:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise PlaywrightNotAvailable(
                "Playwright kurulu değil. Kurulum için: "
                "pip install playwright && playwright install chromium"
            ) from error

        self._playwright = sync_playwright().start()

        try:
            # Önce gerçek Chrome kanalını dene ("Chrome kontrolü").
            return self._playwright.chromium.launch(
                channel="chrome",
                headless=self.headless,
            )
        except Exception:
            # Sistemde Chrome yoksa Playwright'ın kendi Chromium'una düş.
            return self._playwright.chromium.launch(headless=self.headless)

    def stop(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        self._pages = []
        self._active_index = -1

    def _ensure_started(self) -> None:
        if not self.is_started:
            self.start()

    # --- Sekme yönetimi ---------------------------------------------------

    @property
    def active_page(self) -> Any:
        self._ensure_started()
        return self._pages[self._active_index]

    def new_tab(self) -> int:
        self._ensure_started()
        page = self._browser.new_page()
        self._pages.append(page)
        self._active_index = len(self._pages) - 1
        return self._active_index

    def switch_tab(self, index: int) -> bool:
        self._ensure_started()

        if 0 <= index < len(self._pages):
            self._active_index = index
            return True

        return False

    def close_tab(self, index: Optional[int] = None) -> bool:
        self._ensure_started()
        target = self._active_index if index is None else index

        if not (0 <= target < len(self._pages)):
            return False

        try:
            self._pages[target].close()
        except Exception:
            pass

        del self._pages[target]

        if not self._pages:
            self._active_index = -1
        elif self._active_index >= len(self._pages):
            self._active_index = len(self._pages) - 1

        return True

    def list_tabs(self) -> list[dict]:
        self._ensure_started()

        tabs = []
        for index, page in enumerate(self._pages):
            try:
                title = page.title()
            except Exception:
                title = ""

            tabs.append(
                {
                    "index": index,
                    "url": getattr(page, "url", ""),
                    "title": title,
                    "active": index == self._active_index,
                }
            )

        return tabs

    # --- Gezinme / eylemler --------------------------------------------

    def goto(self, url: str) -> str:
        if not url:
            raise ValueError("URL belirtilmedi.")

        page = self.active_page
        page.goto(url)
        return getattr(page, "url", url)

    def search(self, query: str, engine: str = "google") -> str:
        if not query:
            raise ValueError("Arama metni belirtilmedi.")

        template = self.SEARCH_ENGINES.get(engine, self.SEARCH_ENGINES["google"])
        target_url = template.format(query=quote_plus(query))
        return self.goto(target_url)

    def read_page(self) -> dict:
        page = self.active_page

        try:
            title = page.title()
        except Exception:
            title = ""

        try:
            text = page.inner_text("body")
        except Exception:
            text = ""

        return {
            "url": getattr(page, "url", ""),
            "title": title,
            "text": text,
        }

    def click(self, selector: str) -> bool:
        if not selector:
            raise ValueError("Tıklanacak eleman belirtilmedi.")

        page = self.active_page
        page.click(selector)
        return True

    def download(self, trigger_selector: str, save_path: str) -> str:
        if not trigger_selector:
            raise ValueError("İndirmeyi tetikleyecek eleman belirtilmedi.")
        if not save_path:
            raise ValueError("Kayıt yolu belirtilmedi.")

        page = self.active_page
        destination = Path(save_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        with page.expect_download() as download_info:
            page.click(trigger_selector)

        download = download_info.value
        download.save_as(str(destination))
        return str(destination)

    def screenshot(self, save_path: str) -> str:
        if not save_path:
            raise ValueError("Kayıt yolu belirtilmedi.")

        page = self.active_page
        destination = Path(save_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(destination))
        return str(destination)
