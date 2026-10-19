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
        """Find public short-form references without downloading/reusing media.

        YouTube Shorts, TikTok and Instagram Reels are reference-only inputs:
        title/URL/description/duration/engagement metadata may inform topic,
        hook, pacing and packaging decisions, but media bytes/audio are never
        copied by this research path.
        """
        query = str(query or "").strip()
        if not query:
            return {"success": False, "query": "", "results": [], "message": "Video arama metni boş."}

        try:
            requested_timeout = float(timeout_seconds)
            timeout = max(0.01, min(WEB_SEARCH_TIMEOUT_SECONDS, requested_timeout))
            client = DDGS(timeout=timeout)
            results = []
            seen = set()

            def platform_for(url: str, provider: str = "") -> str:
                lowered = (url + " " + provider).casefold()
                if "tiktok.com" in lowered or "tiktok" in lowered:
                    return "TikTok"
                if "instagram.com/reel" in lowered or "instagram" in lowered:
                    return "Instagram Reels"
                if "youtube.com" in lowered or "youtu.be" in lowered or "youtube" in lowered:
                    return "YouTube"
                return provider or "Web video"

            def append(item: dict, url: str, *, fallback_platform: str = "") -> None:
                url = str(url or "").strip()
                if not url or url in seen:
                    return
                seen.add(url)
                provider = str(item.get("provider") or item.get("source") or fallback_platform or "").strip()
                results.append({
                    "title": str(item.get("title") or "").strip(),
                    "url": url,
                    "summary": str(item.get("description") or item.get("body") or item.get("snippet") or "").strip(),
                    "published_at": str(item.get("published") or item.get("date") or "").strip(),
                    "publisher": str(item.get("publisher") or item.get("uploader") or provider).strip(),
                    "provider": provider,
                    "platform": platform_for(url, provider),
                    "duration": str(item.get("duration") or "").strip(),
                    "statistics": item.get("statistics") if isinstance(item.get("statistics"), dict) else {},
                })

            try:
                raw_results = client.videos(
                    query, region="ch-de", safesearch="moderate", timelimit=timelimit,
                    duration="short", max_results=max_results,
                )
                for item in raw_results or []:
                    append(item, item.get("content") or item.get("embed_url") or item.get("url"))
            except Exception:
                pass

            # Always supplement with explicit public short-form surfaces so
            # a generic video backend cannot silently bias discovery toward a
            # single platform. Metadata only; no download happens here.
            surface_queries = (
                ("YouTube", f"site:youtube.com/shorts {query}"),
                ("TikTok", f"site:tiktok.com {query} video"),
                ("Instagram Reels", f"site:instagram.com/reel {query}"),
            )
            target = max(max_results * 2, 6)
            for platform, surface_query in surface_queries:
                if len(results) >= target:
                    break
                try:
                    fallback = client.text(
                        surface_query, region="ch-de", safesearch="moderate",
                        max_results=max(2, min(max_results, 4)),
                    )
                except Exception:
                    continue
                for item in fallback or []:
                    url = str(item.get("href") or item.get("url") or "").strip()
                    lowered = url.casefold()
                    valid = (
                        (platform == "YouTube" and ("youtube.com/shorts/" in lowered or "youtu.be/" in lowered))
                        or (platform == "TikTok" and "tiktok.com/" in lowered)
                        or (platform == "Instagram Reels" and "instagram.com/reel" in lowered)
                    )
                    if valid:
                        append(item, url, fallback_platform=platform)

            results = results[:target]
            return {
                "success": bool(results), "query": query, "results": results,
                "message": (
                    f"{len(results)} kısa-video format referansı bulundu."
                    if results else "Kısa-video format referansı bulunamadı."
                ),
            }
        except Exception as error:
            return {
                "success": False, "query": query, "results": [],
                "message": f"Video araması başarısız: {error}",
            }
