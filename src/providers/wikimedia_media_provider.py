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
        try:
            response = requests.get(
                _API_URL,
                params={
                    "action": "query", "format": "json", "generator": "search",
                    "gsrsearch": str(prompt or "")[:500], "gsrnamespace": 6, "gsrlimit": 12,
                    "prop": "imageinfo", "iiprop": "url|mime|extmetadata",
                    "iiurlwidth": max(720, min(int(width), 1600)), "origin": "*",
                },
                headers={"User-Agent": _USER_AGENT},
                timeout=(10, 30),
            )
            response.raise_for_status()
            pages = (response.json().get("query") or {}).get("pages") or {}
            for page in pages.values():
                info = next(iter(page.get("imageinfo") or ()), None)
                if not info or not str(info.get("mime", "")).startswith("image/"):
                    continue
                metadata = info.get("extmetadata") or {}
                license_name = _plain((metadata.get("LicenseShortName") or {}).get("value"))
                if not _license_allowed(license_name):
                    continue
                image_url = str(info.get("thumburl") or info.get("url") or "").strip()
                if not image_url:
                    continue
                image = requests.get(image_url, headers={"User-Agent": _USER_AGENT}, timeout=(10, 45))
                image.raise_for_status()
                content = image.content
                if len(content) < 5000:
                    continue
                source_url = str(info.get("descriptionurl") or "").strip()
                author = _plain((metadata.get("Artist") or {}).get("value"))
                license_url = _plain((metadata.get("LicenseUrl") or {}).get("value"))
                return MediaGenerationResult(
                    True, self.provider_id, model_id, TEXT_TO_IMAGE,
                    content_bytes=content, content_url=image_url,
                    duration_seconds=round(time.monotonic() - started, 2), cost_class="free",
                    provenance={
                        "generation_type": "licensed_stock_retrieval",
                        "source_url": source_url,
                        "author": author,
                        "license": license_name,
                        "license_url": license_url,
                        "attribution_required": "public domain" not in license_name.casefold()
                        and "cc0" not in license_name.casefold(),
                    },
                )
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_IMAGE,
                error="No reusable Public Domain/CC0/CC BY Commons image matched the scene",
                duration_seconds=round(time.monotonic() - started, 2), cost_class="free",
            )
        except (requests.RequestException, ValueError, TypeError) as error:
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_IMAGE,
                error=f"Wikimedia licensed-media search failed: {error}",
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
