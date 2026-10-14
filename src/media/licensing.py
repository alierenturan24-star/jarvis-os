from __future__ import annotations


EXTERNAL_LICENSED_MEDIA_CUES = (
    "public domain",
    "cc0",
    "cc by",
    "wikimedia commons",
    "yeniden kullanıma açık",
    "yeniden kullanima acik",
    "lisanslı gerçek medya",
    "lisansli gercek medya",
    "lisanslı gerçek görsel",
    "lisansli gercek gorsel",
    "lisanslı gerçek video",
    "lisansli gercek video",
    "lisanslı medya",
    "lisansli medya",
)


def requires_external_licensed_media(text: str | None) -> bool:
    """Return whether the request requires reused, licensed real media.

    Original locally-rendered cards can be copyright-safe, but they do not
    satisfy a request for *real licensed media*.  Production and completion
    use this same predicate so they cannot disagree about that distinction.
    """

    lowered = str(text or "").casefold()
    return any(cue in lowered for cue in EXTERNAL_LICENSED_MEDIA_CUES)


def is_allowed_reuse_license(name: str | None) -> bool:
    """Licenses the current attribution/export path can safely preserve."""

    lowered = str(name or "").casefold().replace("_", " ")
    if "-sa" in lowered or " by-sa" in lowered or "-nc" in lowered or " by-nc" in lowered:
        return False
    return (
        "public domain" in lowered
        or "cc0" in lowered
        or "cc by" in lowered
        or "cc-by" in lowered
    )
