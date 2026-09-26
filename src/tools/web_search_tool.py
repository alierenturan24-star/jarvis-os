from typing import Any

from ddgs import DDGS

from src.config.settings import Settings
from src.tools.base_tool import BaseTool

# Sprint: research/production pipeline audit -- now configurable/bounded via
# Settings.RESEARCH_PROVIDER_TIMEOUT_SECONDS (same fail-closed _env_float
# pattern as CLAUDE_CODE_TIMEOUT_SECONDS); this alias is kept so existing
# callers importing the module-level constant keep working.
WEB_SEARCH_TIMEOUT_SECONDS = Settings.RESEARCH_PROVIDER_TIMEOUT_SECONDS


class WebSearchTool(BaseTool):

    def __init__(self) -> None:
        super().__init__(
            name="Web Search",
            description="İnternetten gerçek arama sonuçları toplar.",
            requires_confirmation=False,
        )

    def execute(self, **kwargs: Any) -> dict:

        query = str(kwargs.get("query", "")).strip()
        max_results = int(kwargs.get("max_results", 5))

        if not query:
            return {
                "success": False,
                "query": "",
                "results": [],
                "message": "Arama metni boş.",
            }

        try:
            # DDGS'nin istemci timeout'u verilmezse DNS/ağ katmanında
            # sınırsız bekleyebilir. Hata mevcut güvenli sonuç yoluna düşer.
            requested_timeout = float(kwargs.get("timeout_seconds", WEB_SEARCH_TIMEOUT_SECONDS))
            timeout = max(0.01, min(WEB_SEARCH_TIMEOUT_SECONDS, requested_timeout))
            raw_results = DDGS(timeout=timeout).text(
                query,
                region="tr-tr",
                safesearch="moderate",
                max_results=max_results,
            )

            results = []

            for item in raw_results or []:
                results.append(
                    {
                        "title": str(item.get("title", "")).strip(),
                        "url": str(
                            item.get("href")
                            or item.get("url")
                            or ""
                        ).strip(),
                        "summary": str(
                            item.get("body")
                            or item.get("snippet")
                            or ""
                        ).strip(),
                    }
                )

            if not results:
                return {
                    "success": False,
                    "query": query,
                    "results": [],
                    "message": "Arama sonucu bulunamadı.",
                }

            return {
                "success": True,
                "query": query,
                "results": results,
                "message": f"{len(results)} arama sonucu bulundu.",
            }

        except Exception as error:
            return {
                "success": False,
                "query": query,
                "results": [],
                "message": f"Web araması başarısız: {error}",
            }

    def search(
        self,
        query: str,
        max_results: int = 5,
        timeout_seconds: float = WEB_SEARCH_TIMEOUT_SECONDS,
    ) -> dict:

        return self.execute(
            query=query,
            max_results=max_results,
            timeout_seconds=timeout_seconds,
        )

    def search_news(
        self,
        query: str,
        max_results: int = 5,
        timeout_seconds: float = WEB_SEARCH_TIMEOUT_SECONDS,
        timelimit: str = "w",
    ) -> dict:
        """Return dated news results for current-event research.

        A normal web result usually has no machine-readable publication date.
        Current-event missions must not infer freshness from that absence, so
        they use DDGS' news adapter and preserve its date/source provenance.
        """
        query = str(query or "").strip()
        if not query:
            return {"success": False, "query": "", "results": [], "message": "Arama metni boş."}

        try:
            requested_timeout = float(timeout_seconds)
            timeout = max(0.01, min(WEB_SEARCH_TIMEOUT_SECONDS, requested_timeout))
            raw_results = DDGS(timeout=timeout).news(
                query,
                region="wt-wt",
                safesearch="moderate",
                timelimit=timelimit,
                max_results=max_results,
            )
            results = []
            for item in raw_results or []:
                results.append({
                    "title": str(item.get("title", "")).strip(),
                    "url": str(item.get("url") or item.get("href") or "").strip(),
                    "summary": str(item.get("body") or item.get("snippet") or "").strip(),
                    "published_at": str(
                        item.get("date") or item.get("published_at") or item.get("published") or ""
                    ).strip(),
                    "publisher": str(item.get("source") or "").strip(),
                })
            if not results:
                return {
                    "success": False, "query": query, "results": [],
                    "message": "Tarihli haber sonucu bulunamadı.",
                }
            return {
                "success": True, "query": query, "results": results,
                "message": f"{len(results)} tarihli haber sonucu bulundu.",
            }
        except Exception as error:
            return {
                "success": False, "query": query, "results": [],
                "message": f"Haber araması başarısız: {error}",
            }

    def search_videos(
        self,
        query: str,
        max_results: int = 5,
        timeout_seconds: float = WEB_SEARCH_TIMEOUT_SECONDS,
        timelimit: str = "w",
    ) -> dict:
        """Find public video references without downloading/reusing media.

        Results are metadata-only (title, URL, duration, publisher and any
        engagement statistics the search backend exposes).  They exist solely
        so downstream planning can learn abstract hook/pacing/story patterns;
        no thumbnail, audio, transcript or video bytes are copied.
        """

        query = str(query or "").strip()
        if not query:
            return {"success": False, "query": "", "results": [], "message": "Video arama metni boş."}

        try:
            requested_timeout = float(timeout_seconds)
            timeout = max(0.01, min(WEB_SEARCH_TIMEOUT_SECONDS, requested_timeout))
            client = DDGS(timeout=timeout)
            raw_results = client.videos(
                query, region="ch-de", safesearch="moderate", timelimit=timelimit,
                duration="short", max_results=max_results,
            )
            results = []
            for item in raw_results or []:
                url = str(item.get("content") or item.get("embed_url") or "").strip()
                if not url:
                    continue
                results.append({
                    "title": str(item.get("title") or "").strip(),
                    "url": url,
                    "summary": str(item.get("description") or "").strip(),
                    "published_at": str(item.get("published") or "").strip(),
                    "publisher": str(item.get("publisher") or item.get("uploader") or "").strip(),
                    "provider": str(item.get("provider") or "").strip(),
                    "duration": str(item.get("duration") or "").strip(),
                    "statistics": item.get("statistics") if isinstance(item.get("statistics"), dict) else {},
                })

            # Some DDGS backends temporarily return no video payload.  A
            # metadata-only YouTube Shorts text search is a safe fallback and
            # still proves that a real public reference URL was found.
            if not results:
                fallback = client.text(
                    f"site:youtube.com/shorts {query}", region="ch-de",
                    safesearch="moderate", max_results=max_results,
                )
                for item in fallback or []:
                    url = str(item.get("href") or item.get("url") or "").strip()
                    if "youtube.com/shorts/" not in url.casefold():
                        continue
                    results.append({
                        "title": str(item.get("title") or "").strip(),
                        "url": url,
                        "summary": str(item.get("body") or item.get("snippet") or "").strip(),
                        "published_at": "", "publisher": "YouTube", "provider": "YouTube",
                        "duration": "", "statistics": {},
                    })

            return {
                "success": bool(results), "query": query, "results": results,
                "message": (
                    f"{len(results)} video format referansı bulundu."
                    if results else "Video format referansı bulunamadı."
                ),
            }
        except Exception as error:
            return {
                "success": False, "query": query, "results": [],
                "message": f"Video araması başarısız: {error}",
            }
