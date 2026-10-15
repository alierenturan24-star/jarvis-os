from __future__ import annotations

import re
import time
from html import unescape

import requests

from src.media.capability_model import (
    MediaGenerationResult, MediaModelProfile, TEXT_TO_IMAGE, TEXT_TO_VIDEO,
)
from src.providers.media_provider_base import MediaProvider


_API_URL = "https://commons.wikimedia.org/w/api.php"
_USER_AGENT = "JarvisOS/1.0 (licensed-media-retrieval; local video production)"
_ALLOWED_LICENSES = ("public domain", "cc0", "cc by ", "cc-by-")


def _plain(value: object) -> str:
    return re.sub(r"<[^>]+>", "", unescape(str(value or ""))).strip()


def _license_allowed(name: str) -> bool:
    lowered = f" {name.casefold().replace('_', ' ')} "
    if "-sa" in lowered or " by-sa" in lowered or "-nc" in lowered or " by-nc" in lowered:
        return False
    return any(marker in lowered for marker in _ALLOWED_LICENSES)



_SCENE_STOPWORDS = {
    "portre", "fotoğraf", "fotograf", "arşiv", "arsiv", "görüntü", "goruntu",
    "görsel", "gorsel", "dikey", "çekim", "cekim", "yakın", "yakin",
    "plan", "karesi", "basın", "basin", "genel", "salonu", "sembolik",
    "uygun", "wikimedia", "commons", "lisans", "licensed", "vertical",
    "photo", "portrait", "footage", "scene", "stock", "image", "video",
}


def _search_queries(description: str) -> tuple[str, ...]:
    """Small, subject-focused Commons queries; never search a whole film brief.

    Keep named people/buildings specific. A broad unrelated photograph is not
    adequate visual evidence merely because it has an acceptable license.
    """
    raw = _plain(description)[:500]
    if not raw:
        return ()
    # Remove license/source directions, not the actual subject of the shot.
    raw = re.sub(r"\([^)]*(?:wikimedia|commons|cc0|cc[\s-]*by|public domain)[^)]*\)",
                 " ", raw, flags=re.IGNORECASE)
    aliases = re.findall(r"\(([^()]{3,60})\)", raw)
    subject = re.sub(r"\([^()]*\)", " ", raw)
    subject = re.sub(r"[/|,;]", " ", subject)
    words = re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", subject, flags=re.UNICODE)
    meaningful = [word for word in words
                  if word.casefold() not in _SCENE_STOPWORDS and len(word) > 2]
    cleaned = " ".join(meaningful[:6])
    folded = raw.casefold()
    candidates: list[str] = []
    for alias in aliases:
        if not re.search(r"(?i)\b(?:cc0|cc\s*by|commons|wikimedia)\b", alias):
            candidates.append(alias.strip())
    # Exact recognizable institutions and objects in multiple languages.
    if "bundeshaus" in folded or ("bern" in folded and "federal" in folded):
        candidates.append("Bundeshaus Bern")
    if ("isviçre" in folded or "isvicre" in folded) and (
        "parlamento" in folded or "federal saray" in folded
    ):
        candidates.append("Bundeshaus Bern")
    if ("isviçre" in folded or "isvicre" in folded) and "bayra" in folded:
        candidates.append("Flag of Switzerland")
    # Prefer exact proper-name pairs for a person over broad keywords.
    names = re.findall(
        r"\b[A-ZÀ-ÖØ-ÞÇĞİÖŞÜ][a-zà-öø-ÿçğıöşü'-]+"
        r"\s+[A-ZÀ-ÖØ-ÞÇĞİÖŞÜ][a-zà-öø-ÿçğıöşü'-]+\b", subject
    )
    candidates.extend(names[:2])
    if cleaned:
        candidates.append(cleaned)
        if len(meaningful) > 4:
            candidates.append(" ".join(meaningful[:4]))
    return tuple(dict.fromkeys(q for q in candidates if len(q.strip()) >= 3))[:4]


class WikimediaMediaProvider(MediaProvider):
    """Key-free retrieval of reusable Commons images/clips with license evidence.

    This provider does not pretend stock retrieval is AI generation. It joins
    the existing media provider boundary only for a FREE_ONLY production run,
    and every selected image carries its source, author, and license into the
    production manifest.
    """

    def __init__(self) -> None:
        super().__init__("wikimedia_commons")

    def capabilities(self) -> tuple[str, ...]:
        return (TEXT_TO_IMAGE, TEXT_TO_VIDEO)

    def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    def profiles(self) -> tuple[MediaModelProfile, ...]:
        common = dict(
            provider_id=self.provider_id, availability=True, auth_required=False,
            cost_class="free", free_tier=True, subscription_cli=False,
            local_or_remote="remote", quality_tier=66, speed_tier=70,
        )
        return (
            MediaModelProfile(
                model_id="licensed-image-search-v1", capabilities=(TEXT_TO_IMAGE,),
                notes="Wikimedia Commons licensed image retrieval; not generative AI.",
                **common,
            ),
            MediaModelProfile(
                model_id="licensed-video-search-v1", capabilities=(TEXT_TO_VIDEO,),
                supports_duration_control=False, supports_audio=True,
                notes="Wikimedia Commons licensed video retrieval; not generative AI.",
                **common,
            ),
        )

    def generate_image(
        self, prompt: str, *, width: int = 1024, height: int = 1024,
        seed: int = 0, model: str | None = None,
    ) -> MediaGenerationResult:
        del height, seed
        model_id = model or "licensed-image-search-v1"
        started = time.monotonic()
        queries = _search_queries(prompt)
        attempted = []
        try:
            for query in queries:
                attempted.append(query)
                response = requests.get(
                    _API_URL,
                    params={
                        "action": "query", "format": "json", "generator": "search",
                        "gsrsearch": query, "gsrnamespace": 6, "gsrlimit": 30,
                        "prop": "imageinfo", "iiprop": "url|mime|extmetadata",
                        "iiurlwidth": max(720, min(int(width), 1600)),
                    },
                    headers={"User-Agent": _USER_AGENT},
                    timeout=(7, 15),
                )
                response.raise_for_status()
                pages = (response.json().get("query") or {}).get("pages") or {}
                # Commons returns page mappings whose insertion order is not
                # guaranteed to reflect the search rank.
                ordered = sorted(pages.values(), key=lambda item: item.get("index", 9999))
                for page in ordered:
                    info = next(iter(page.get("imageinfo") or ()), None)
                    if not info or str(info.get("mime", "")).lower() not in (
                        "image/jpeg", "image/png", "image/webp",
                    ):
                        continue
                    metadata = info.get("extmetadata") or {}
                    license_name = _plain((metadata.get("LicenseShortName") or {}).get("value"))
                    if not _license_allowed(license_name):
                        continue
                    source_url = str(info.get("descriptionurl") or "").strip()
                    author = _plain((metadata.get("Artist") or {}).get("value"))
                    license_url = _plain((metadata.get("LicenseUrl") or {}).get("value"))
                    # Without a file page the attribution cannot be audited.
                    # CC BY additionally requires usable author/license data.
                    is_public = "public domain" in license_name.casefold() or "cc0" in license_name.casefold()
                    if not source_url.startswith("https://commons.wikimedia.org/"):
                        continue
                    if not is_public and (not author or not license_url):
                        continue
                    image_url = str(info.get("thumburl") or info.get("url") or "").strip()
                    if not image_url.startswith("https://"):
                        continue
                    try:
                        image = requests.get(
                            image_url, headers={"User-Agent": _USER_AGENT}, timeout=(7, 30)
                        )
                        image.raise_for_status()
                    except requests.RequestException:
                        continue
                    if len(image.content) < 5000:
                        continue
                    return MediaGenerationResult(
                        True, self.provider_id, model_id, TEXT_TO_IMAGE,
                        content_bytes=image.content, content_url=image_url,
                        duration_seconds=round(time.monotonic() - started, 2), cost_class="free",
                        provenance={
                            "generation_type": "licensed_stock_retrieval",
                            "source_url": source_url, "author": author,
                            "license": license_name, "license_url": license_url,
                            "search_query": query,
                            "attribution_required": not is_public,
                        },
                    )
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_IMAGE,
                error="No reusable Public Domain/CC0/CC BY Commons image matched "
                      f"subject-focused queries: {attempted!r}",
                duration_seconds=round(time.monotonic() - started, 2), cost_class="free",
            )
        except (requests.RequestException, ValueError, TypeError) as error:
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_IMAGE,
                error=f"Wikimedia licensed-media search failed after {attempted!r}: {error}",
                duration_seconds=round(time.monotonic() - started, 2), cost_class="free",
            )

    def generate_video_clip(
        self, prompt: str, *, max_bytes: int = 50 * 1024 * 1024,
        model: str | None = None,
    ) -> MediaGenerationResult:
        """Retrieve one genuinely reusable Commons clip, never a YouTube rip.

        CC BY-SA/NC assets are deliberately rejected because the production
        pipeline does not implement share-alike propagation or non-commercial
        enforcement.  The returned provenance is persisted into the final
        production manifest by ``GeneralProductionBuilder``.
        """

        model_id = model or "licensed-video-search-v1"
        started = time.monotonic()
        try:
            response = requests.get(
                _API_URL,
                params={
                    "action": "query", "format": "json", "generator": "search",
                    "gsrsearch": f"{str(prompt or '')[:420]} filetype:video",
                    "gsrnamespace": 6, "gsrlimit": 16,
                    "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata", "origin": "*",
                },
                headers={"User-Agent": _USER_AGENT}, timeout=(10, 30),
            )
            response.raise_for_status()
            pages = (response.json().get("query") or {}).get("pages") or {}
            for page in pages.values():
                info = next(iter(page.get("imageinfo") or ()), None)
                if not info or not str(info.get("mime", "")).startswith("video/"):
                    continue
                metadata = info.get("extmetadata") or {}
                license_name = _plain((metadata.get("LicenseShortName") or {}).get("value"))
                if not _license_allowed(license_name):
                    continue
                size = int(info.get("size") or 0)
                if size and size > max_bytes:
                    continue
                media_url = str(info.get("url") or "").strip()
                if not media_url:
                    continue
                download = requests.get(
                    media_url, headers={"User-Agent": _USER_AGENT}, timeout=(10, 60), stream=True,
                )
                download.raise_for_status()
                chunks, total = [], 0
                for chunk in download.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        chunks = []
                        break
                    chunks.append(chunk)
                content = b"".join(chunks)
                if len(content) < 10_000:
                    continue
                source_url = str(info.get("descriptionurl") or "").strip()
                author = _plain((metadata.get("Artist") or {}).get("value"))
                license_url = _plain((metadata.get("LicenseUrl") or {}).get("value"))
                return MediaGenerationResult(
                    True, self.provider_id, model_id, TEXT_TO_VIDEO,
                    content_bytes=content, content_url=media_url,
                    duration_seconds=round(time.monotonic() - started, 2), cost_class="free",
                    provenance={
                        "generation_type": "licensed_stock_video_retrieval",
                        "source_url": source_url, "author": author,
                        "license": license_name, "license_url": license_url,
                        "mime": str(info.get("mime") or "video/webm"),
                        "attribution_required": "public domain" not in license_name.casefold()
                        and "cc0" not in license_name.casefold(),
                    },
                )
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_VIDEO,
                error="No reusable Public Domain/CC0/CC BY Commons video matched the scene",
                duration_seconds=round(time.monotonic() - started, 2), cost_class="free",
            )
        except (requests.RequestException, ValueError, TypeError) as error:
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_VIDEO,
                error=f"Wikimedia licensed-video search failed: {error}",
                duration_seconds=round(time.monotonic() - started, 2), cost_class="free",
            )
