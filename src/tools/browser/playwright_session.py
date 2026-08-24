from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote_plus

from src.tools.browser.dom_engine import DomEngine, DomSnapshot, InvalidDomIndexError


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

    Sprint 30B -- Thread Affinity: Playwright'ın senkron API'si, onu
    başlatan işletim sistemi thread'ine bağlıdır (thread-affine);
    ``sync_playwright()``/``Browser``/``BrowserContext``/``Page``
    farklı bir thread'den kullanılırsa sessizce yanlış/eksik sonuç
    üretebilir (bkz. Debug Sprint 30 kanıtı: aynı ``Page`` nesnesi farklı
    thread'lerden sürülünce ``list_elements`` 0 eleman buluyordu, oysa
    aynı sayfa tek thread'den sürülünce onlarca eleman içeriyordu).
    Bu sınıf artık kendi KALICI, TEK worker'lı bir "owner thread"
    (``_owner_executor``) sahipleniyor; gerçek Playwright dokunan HER
    işlem -- hangi dış (ör. ``JobManager``) thread'inden çağrılırsa
    çağrılsın -- her zaman bu aynı owner thread üzerinde çalışır.
    Dışarıdaki genel API (``goto()`` hâlâ senkron ``str`` döner vb.)
    ve tüm çağıran katmanlar (BrowserTool/BrowserAgent/DOM Engine)
    bundan TAMAMEN habersizdir -- hiçbiri değiştirilmedi.
    """

    SEARCH_ENGINES = {
        "google": "https://www.google.com/search?q={query}",
        "duckduckgo": "https://duckduckgo.com/?q={query}",
        "github": "https://github.com/search?q={query}",
        "youtube": "https://www.youtube.com/results?search_query={query}",
    }
    ACTION_TIMEOUT_MS = 15_000
    NAVIGATION_TIMEOUT_MS = 30_000

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

        # DOM Engine v1: görev-anlık, önbelleksiz index -> eleman haritası.
        # Sayfa değiştiren her eylemde (goto/sekme değişimi/click_index) sıfırlanır.
        self._dom_engine = DomEngine()
        self._dom_snapshot: Optional[DomSnapshot] = None

        # Sprint 30B: kalıcı, tek-worker'lı owner thread mekanizması.
        # Yalnızca ilk gerçek kullanımda (lazy) oluşturulur.
        self._owner_executor: Optional[ThreadPoolExecutor] = None
        self._owner_thread_id: Optional[int] = None
        self._owner_setup_lock = threading.Lock()

    # --- Sprint 30B: Owner thread altyapısı -------------------------------

    def _ensure_owner(self) -> None:
        """Kalıcı tek-worker'lı owner executor'ı (yoksa) oluşturur ve
        owner thread'in kimliğini (``threading.get_ident()``) öğrenir."""

        if self._owner_executor is not None:
            return

        with self._owner_setup_lock:
            if self._owner_executor is not None:
                return

            executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="PlaywrightSessionOwner"
            )
            # ThreadPoolExecutor(max_workers=1), ömrü boyunca DAİMA aynı
            # tek worker thread'i kullanır -- bu, gönderilen ilk (bilgi
            # amaçlı) göreve ait thread kimliğini öğrenmemizi, sonraki
            # her çağrının GERÇEKTEN aynı thread'e düştüğünü garanti
            # etmemizi sağlar (yeniden-giriş/deadlock tespiti için).
            owner_thread_id = executor.submit(threading.get_ident).result()

            self._owner_executor = executor
            self._owner_thread_id = owner_thread_id

    def _run_on_owner(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """``fn``'i HER ZAMAN owner thread üzerinde çalıştırır.

        Çağıran zaten owner thread'in ta kendisiyse (yeniden giriş --
        ör. ``goto()`` içinden ``active_page`` -> ``start()``), ``fn``
        DOĞRUDAN çağrılır; aksi halde owner executor'a submit edilip
        sonucu (veya fırlatılan istisnayı, ``Future.result()`` zaten
        orijinal istisnayı olduğu gibi yeniden fırlatır) beklenir.
        Bu, owner thread'in kendi kendine submit edip kendini
        beklemesinden kaynaklanacak KİLİTLENMEYİ önler."""

        self._ensure_owner()

        if threading.get_ident() == self._owner_thread_id:
            return fn(*args, **kwargs)

        future = self._owner_executor.submit(fn, *args, **kwargs)
        return future.result()

    # --- Yaşam döngüsü --------------------------------------------------

    @property
    def is_started(self) -> bool:
        return self._browser is not None

    def start(self) -> None:
        if self.is_started:
            return
        self._run_on_owner(self._start_impl)

    def _start_impl(self) -> None:
        self._browser = (
            self._browser_launcher()
            if self._browser_launcher is not None
            else self._launch_real_chrome()
        )

        page = self._browser.new_page()
        self._configure_page_timeouts(page)
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
        if self._owner_executor is None:
            # Hiç başlatılmamış (veya zaten durdurulmuş): temizlenecek
            # gerçek bir Playwright kaynağı yok -- eski davranışla aynı
            # şekilde yalnızca durumu sıfırla, yeni bir owner thread
            # YARATIP hemen kapatmaya gerek yok.
            self._stop_playwright_impl()
            return

        self._run_on_owner(self._stop_playwright_impl)

        # Owner executor'ı kapat. Eğer bu çağrı owner thread'in
        # İÇİNDEN yapılıyorsa (yeniden giriş), ``wait=True`` kendi
        # kendini beklemeye (kilitlenmeye) yol açar -- bu durumda
        # ``wait=False`` kullanılır; worker zaten mevcut işini
        # (bu ``stop()`` çağrısını) bitirir bitirmez doğal olarak sona
        # erer, thread sızıntısı OLMAZ.
        if threading.get_ident() == self._owner_thread_id:
            self._owner_executor.shutdown(wait=False)
        else:
            self._owner_executor.shutdown(wait=True)

        self._owner_executor = None
        self._owner_thread_id = None

    def _stop_playwright_impl(self) -> None:
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
        return self._run_on_owner(self._new_tab_impl)

    def _new_tab_impl(self) -> int:
        self._ensure_started()
        self._dom_snapshot = None
        page = self._browser.new_page()
        self._configure_page_timeouts(page)
        self._pages.append(page)
        self._active_index = len(self._pages) - 1
        return self._active_index

    def _configure_page_timeouts(self, page: Any) -> None:
        """Bound real Playwright calls while preserving injected test pages."""
        if hasattr(page, "set_default_timeout"):
            page.set_default_timeout(self.ACTION_TIMEOUT_MS)
        if hasattr(page, "set_default_navigation_timeout"):
            page.set_default_navigation_timeout(self.NAVIGATION_TIMEOUT_MS)

    def switch_tab(self, index: int) -> bool:
        return self._run_on_owner(self._switch_tab_impl, index)

    def _switch_tab_impl(self, index: int) -> bool:
        self._ensure_started()

        if 0 <= index < len(self._pages):
            self._active_index = index
            self._dom_snapshot = None
            return True

        return False

    def close_tab(self, index: Optional[int] = None) -> bool:
        return self._run_on_owner(self._close_tab_impl, index)

    def _close_tab_impl(self, index: Optional[int]) -> bool:
        self._ensure_started()
        self._dom_snapshot = None
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
        return self._run_on_owner(self._list_tabs_impl)

    def _list_tabs_impl(self) -> list[dict]:
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
        return self._run_on_owner(self._goto_impl, url)

    def _goto_impl(self, url: str) -> str:
        if not url:
            raise ValueError("URL belirtilmedi.")

        page = self.active_page
        self._dom_snapshot = None
        page.goto(url)
        return getattr(page, "url", url)

    def search(self, query: str, engine: str = "google") -> str:
        # NOT: kasıtlı olarak AYRICA ``_run_on_owner`` ile sarmalanmadı --
        # tek gerçek Playwright işlemi zaten ``self.goto()`` üzerinden
        # yapılıyor ve ``goto()`` kendi başına owner thread'e yönlendiriyor
        # (bkz. yukarısı). Burada ekstra bir dispatch, gereksiz bir
        # yeniden-giriş katmanı eklemekten başka bir şey yapmazdı.
        if not query:
            raise ValueError("Arama metni belirtilmedi.")

        template = self.SEARCH_ENGINES.get(engine, self.SEARCH_ENGINES["google"])
        target_url = template.format(query=quote_plus(query))
        return self.goto(target_url)

    def read_page(self) -> dict:
        return self._run_on_owner(self._read_page_impl)

    def _read_page_impl(self) -> dict:
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
        return self._run_on_owner(self._click_impl, selector)

    def _click_impl(self, selector: str) -> bool:
        if not selector:
            raise ValueError("Tıklanacak eleman belirtilmedi.")

        page = self.active_page
        page.click(selector)
        return True

    def download(self, trigger_selector: str, save_path: str) -> str:
        return self._run_on_owner(self._download_impl, trigger_selector, save_path)

    def _download_impl(self, trigger_selector: str, save_path: str) -> str:
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
        return self._run_on_owner(self._screenshot_impl, save_path)

    def _screenshot_impl(self, save_path: str) -> str:
        if not save_path:
            raise ValueError("Kayıt yolu belirtilmedi.")

        page = self.active_page
        destination = Path(save_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(destination))
        return str(destination)

    # --- DOM Engine v1 -----------------------------------------------------

    def list_elements(self) -> str:
        return self._run_on_owner(self._list_elements_impl)

    def _list_elements_impl(self) -> str:
        """Aktif sayfadaki etkileşimli elemanları sıfırdan tarar ve
        önceki index haritasının tamamen yerine geçen yeni bir
        ``DomSnapshot`` üretir (önbellek yok)."""

        page = self.active_page
        self._dom_snapshot = self._dom_engine.build_snapshot(page)
        return self._dom_snapshot.render()

    def click_index(self, index: int) -> str:
        return self._run_on_owner(self._click_index_impl, index)

    def _click_index_impl(self, index: int) -> str:
        """``list_elements`` ile üretilmiş güncel index haritasındaki bir
        elemana tıklar. Harita yoksa veya index geçersizse/eskiyse
        ``InvalidDomIndexError`` yükseltir."""

        self._ensure_started()

        if self._dom_snapshot is None:
            raise InvalidDomIndexError(
                "Aktif bir eleman listesi yok. Önce 'list_elements' çalıştırın."
            )

        description = self._dom_snapshot.describe(index)
        locator = self._dom_snapshot.resolve(index)

        locator.click()

        # Tıklama sayfayı değiştirmiş olabilir (navigasyon, yeni içerik vb.);
        # bir sonraki click_index'in bayat bir haritayı kullanmasını önlemek
        # için mevcut haritayı tamamen geçersiz kılıyoruz.
        self._dom_snapshot = None

        return description
