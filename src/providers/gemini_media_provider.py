from __future__ import annotations

import base64
import time

import requests

from src.config.settings import Settings
from src.media.capability_model import MediaGenerationResult, MediaModelProfile, TEXT_TO_IMAGE
from src.providers.media_provider_base import MediaProvider


class GeminiImageProvider(MediaProvider):
    """Gemini native image generation through the documented REST API.

    This is deliberately separate from ``GeminiProvider``: that provider is
    text completion, while this one returns image bytes and participates only
    in the media-provider approval/ranking pipeline.
    """

    def __init__(self) -> None:
        super().__init__("gemini_image")

    def capabilities(self) -> tuple[str, ...]:
        return (TEXT_TO_IMAGE,)

    def is_available(self) -> bool:
        return bool(Settings.GEMINI_API_KEY)

    def unavailable_reason(self) -> str:
        return "" if self.is_available() else "GEMINI_API_KEY not configured -- auth missing"

    @staticmethod
    def _cost_class() -> str:
        # Gemini text has a free quota, but native image output is separately
        # priced.  A distinct provider id keeps the paid-media approval gate
        # truthful without changing text routing.
        from src.providers.cost_optimizer import CostOptimizer
        return CostOptimizer.cost_class("gemini_image")

    def profiles(self) -> tuple[MediaModelProfile, ...]:
        return (MediaModelProfile(
            provider_id=self.provider_id,
            model_id=Settings.GEMINI_IMAGE_MODEL,
            capabilities=(TEXT_TO_IMAGE,),
            availability=self.is_available(),
            auth_required=True,
            cost_class=self._cost_class(),
            free_tier=False,
            subscription_cli=False,
            local_or_remote="remote",
            quality_tier=92,
            speed_tier=82,
            supports_vertical_video=False,
            supports_image_conditioning=False,
            supports_duration_control=False,
            supports_seed=False,
            supports_audio=False,
            notes=(
                "Gemini native image generation. Paid image output; every call "
                "uses the existing paid_media_generation approval gate."
            ),
            unavailable_reason=self.unavailable_reason(),
        ),)

    @staticmethod
    def _aspect_ratio(width: int, height: int) -> str:
        ratio = width / max(height, 1)
        if ratio <= 0.64:
            return "9:16"
        if ratio <= 0.84:
            return "3:4"
        if ratio >= 1.55:
            return "16:9"
        if ratio >= 1.18:
            return "4:3"
        return "1:1"

    def generate_image(
        self, prompt: str, *, width: int = 1024, height: int = 1024,
        seed: int = 0, model: str | None = None,
    ) -> MediaGenerationResult:
        del seed  # Gemini image REST contract does not promise seed control.
        model_id = model or Settings.GEMINI_IMAGE_MODEL
        cost_class = self._cost_class()
        if not self.is_available():
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_IMAGE,
                error=self.unavailable_reason(), cost_class=cost_class,
            )

        started = time.monotonic()
        response = None
        try:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1/models/{model_id}:generateContent",
                headers={
                    "x-goog-api-key": Settings.GEMINI_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "contents": [{"parts": [{"text": prompt[:4000]}]}],
                    "generationConfig": {
                        "responseModalities": ["IMAGE"],
                        "imageConfig": {"aspectRatio": self._aspect_ratio(width, height)},
                    },
                },
                timeout=Settings.REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            for candidate in data.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    inline = part.get("inlineData") or part.get("inline_data") or {}
                    encoded = inline.get("data")
                    if encoded:
                        content = base64.b64decode(encoded)
                        if content:
                            return MediaGenerationResult(
                                True, self.provider_id, model_id, TEXT_TO_IMAGE,
                                content_bytes=content,
                                duration_seconds=round(time.monotonic() - started, 2),
                                cost_class=cost_class,
                            )
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_IMAGE,
                error="Gemini image response did not include usable inline image data",
                duration_seconds=round(time.monotonic() - started, 2),
                cost_class=cost_class,
            )
        except requests.exceptions.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            reason = (
                "Gemini image auth failed" if status in (401, 403)
                else "Gemini image quota/rate limit reached" if status == 429
                else f"Gemini image HTTP error {status}"
            )
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_IMAGE,
                error=reason, duration_seconds=round(time.monotonic() - started, 2),
                cost_class=cost_class,
            )
        except requests.exceptions.Timeout:
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_IMAGE,
                error=f"Gemini image request timed out (limit {Settings.REQUEST_TIMEOUT}s)",
                duration_seconds=round(time.monotonic() - started, 2),
                cost_class=cost_class,
            )
        except (requests.exceptions.RequestException, ValueError, TypeError, KeyError) as error:
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_IMAGE,
                error=f"Gemini image provider error: {error}",
                duration_seconds=round(time.monotonic() - started, 2),
                cost_class=cost_class,
            )
