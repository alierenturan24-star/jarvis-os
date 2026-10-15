from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any


_ALLOWED_LICENSE_MARKERS = (
    "creative commons attribution",
    "cc by",
    "cc-by",
    "cc0",
    "public domain",
)
_REJECT_LICENSE_MARKERS = (
    "cc by-sa", "cc-by-sa", "share alike", "noncommercial", "non-commercial",
    "cc by-nc", "cc-by-nc", "no derivatives", "cc by-nd", "cc-by-nd",
)
_STOPWORDS = {
    "wikimedia", "commons", "public", "domain", "cc0", "lisans", "licensed",
    "video", "görüntü", "goruntu", "çekim", "cekim", "sahne", "dikey",
    "vertical", "footage", "photo", "fotoğraf", "fotograf", "karesi",
}


def _license_allowed(value: object) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip().casefold())
    if not text or any(marker in text for marker in _REJECT_LICENSE_MARKERS):
        return False
    return any(marker in text for marker in _ALLOWED_LICENSE_MARKERS)


def _compact_query(description: str) -> str:
    raw = str(description or "").strip()
    raw = re.sub(r"\([^)]*(?:wikimedia|commons|cc0|cc[\s-]*by|public domain)[^)]*\)",
                 " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"[/|,;:]", " ", raw)
    words = re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", raw, flags=re.UNICODE)
    useful = [word for word in words if len(word) > 2 and word.casefold() not in _STOPWORDS]
    return " ".join(useful[:7]).strip()


@dataclass(frozen=True)
class LicensedYtDlpResult:
    success: bool
    path: str = ""
    error: str = ""
    provenance: dict | None = None
    duration_seconds: float = 0.0


class LicensedYtDlpVideoProvider:
    """Bounded yt-dlp discovery/downloader for explicitly reusable video only.

    This is deliberately NOT a generic "rip any YouTube video" adapter. It
    searches a small candidate set, re-extracts full metadata, and downloads
    only when yt-dlp exposes an allowed Public Domain/CC0/CC BY-style license.
    Missing/standard/ambiguous license metadata is a hard reject.
    """

    provider_id = "yt_dlp_licensed_video"

    def __init__(self, ydl_factory: Callable[[dict], Any] | None = None) -> None:
        self._ydl_factory = ydl_factory

    def _make_ydl(self, options: dict):
        if self._ydl_factory is not None:
            return self._ydl_factory(options)
        from yt_dlp import YoutubeDL
        return YoutubeDL(options)

    @staticmethod
    def _candidate_url(entry: dict) -> str:
        url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
        if url.startswith("http://") or url.startswith("https://"):
            return url
        video_id = str(entry.get("id") or "").strip()
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
        return ""

    def find_and_download(
        self, description: str, output_root: Path, *,
        max_candidates: int = 5, max_duration_seconds: int = 900,
    ) -> LicensedYtDlpResult:
        started = time.monotonic()
        query = _compact_query(description)
        if not query:
            return LicensedYtDlpResult(False, error="yt-dlp search query is empty")

        common = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 15,
            "retries": 1,
            "fragment_retries": 1,
        }
        try:
            with self._make_ydl({**common, "skip_download": True}) as ydl:
                search = ydl.extract_info(f"ytsearch{max_candidates}:{query}", download=False) or {}
            entries = list(search.get("entries") or [])[:max_candidates]
        except Exception as error:
            return LicensedYtDlpResult(
                False, error=f"yt-dlp search failed: {error}",
                duration_seconds=round(time.monotonic() - started, 2),
            )

        rejected: list[str] = []
        selected: dict | None = None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            url = self._candidate_url(entry)
            if not url:
                continue
            try:
                with self._make_ydl({**common, "skip_download": True}) as ydl:
                    info = ydl.extract_info(url, download=False) or {}
            except Exception as error:
                rejected.append(f"{url}: metadata error {error}")
                continue
            license_name = str(info.get("license") or "").strip()
            if not _license_allowed(license_name):
                rejected.append(f"{url}: license={license_name or 'missing'}")
                continue
            duration = float(info.get("duration") or 0.0)
            if duration and duration > max_duration_seconds:
                rejected.append(f"{url}: duration={duration:.0f}s")
                continue
            webpage_url = str(info.get("webpage_url") or url).strip()
            uploader = str(info.get("uploader") or info.get("channel") or "").strip()
            title = str(info.get("title") or "").strip()
            if not webpage_url.startswith(("http://", "https://")) or not uploader or not title:
                rejected.append(f"{url}: attribution metadata incomplete")
                continue
            selected = {
                "url": webpage_url,
                "title": title,
                "author": uploader,
                "license": license_name,
                "duration": duration,
                "id": str(info.get("id") or ""),
            }
            break

        if selected is None:
            return LicensedYtDlpResult(
                False,
                error="No yt-dlp candidate had explicit reusable license metadata; "
                      + "; ".join(rejected[:5]),
                duration_seconds=round(time.monotonic() - started, 2),
            )

        output_root.mkdir(parents=True, exist_ok=True)
        template = str((output_root / "yt-dlp-source.%(ext)s").resolve())
        download_options = {
            **common,
            "outtmpl": template,
            "format": "bestvideo[height<=1080]/best[height<=1080]/best",
            "overwrites": True,
        }
        before = {path.resolve() for path in output_root.glob("yt-dlp-source.*")}
        try:
            with self._make_ydl(download_options) as ydl:
                ydl.extract_info(selected["url"], download=True)
        except Exception as error:
            return LicensedYtDlpResult(
                False, error=f"yt-dlp licensed download failed: {error}",
                duration_seconds=round(time.monotonic() - started, 2),
            )

        candidates = [
            path for path in output_root.glob("yt-dlp-source.*")
            if path.resolve() not in before and path.is_file() and path.stat().st_size > 10_000
        ]
        if not candidates:
            candidates = [
                path for path in output_root.glob("yt-dlp-source.*")
                if path.is_file() and path.stat().st_size > 10_000
            ]
        if not candidates:
            return LicensedYtDlpResult(
                False, error="yt-dlp reported success but no media file was created",
                duration_seconds=round(time.monotonic() - started, 2),
            )
        path = max(candidates, key=lambda item: item.stat().st_size)
        provenance = {
            "generation_type": "licensed_stock_video_retrieval",
            "source_url": selected["url"],
            "author": selected["author"],
            "title": selected["title"],
            "license": selected["license"],
            "license_url": "https://creativecommons.org/licenses/by/3.0/",
            "search_query": query,
            "attribution_required": True,
            "external_media_used": True,
            "downloader": "yt-dlp",
        }
        return LicensedYtDlpResult(
            True, path=str(path.resolve()), provenance=provenance,
            duration_seconds=round(time.monotonic() - started, 2),
        )
