from __future__ import annotations

import time

import requests

from src.config.settings import Settings
from src.media.capability_model import MediaGenerationResult, MediaModelProfile, TEXT_TO_IMAGE
from src.providers.media_provider_base import MediaProvider

# Sprint: multi-provider media capability foundation -- fal.ai FLUX.
#
# Real, documented API contract (verified 2026-08-26 directly against
# fal.ai's own docs: https://fal.ai/docs/model-apis/fast-flux,
# https://fal.ai/models/fal-ai/flux/schnell/api, and the auth docs at
# https://fal.ai/docs/... "Authorization: Key $FAL_KEY"):
#
#   POST {FAL_BASE_URL}/{model}             e.g. https://fal.run/fal-ai/flux/schnell
#   Headers: Authorization: Key <key>, Content-Type: application/json
#   Body:    {"prompt": str, "image_size": {"width": int, "height": int},
#             "num_images": 1, "num_inference_steps": 4,
#             "enable_safety_checker": true, "seed": int (optional)}
#   Response: {"images": [{"url": str, "width": int, "height": int,
#                           "content_type": "image/jpeg"}],
#              "seed": int, "has_nsfw_concepts": [bool], "prompt": str}
#
# schnell is fast enough (1-4 steps) that fal's own auth-docs curl example
# calls it synchronously via fal.run (not the queue.fal.run async workflow
# -- that is reserved here for LTX-2.5 video, see ltx_provider.py). This
# module implements ONLY text_to_image -- fal also hosts LTX-2.5 video, but
# that is the SEPARATE, already-existing LTXMediaProvider; this provider
# never claims a capability it does not genuinely call.
#
# fal.ai issues one account-wide API key valid for every fal-hosted model.
# LTX_API_KEY (see Settings) is already a real fal.ai key -- _api_key()
# below reuses it live (at call time, never baked in at import) when
# FAL_API_KEY itself is unset, so no second .env edit is required.


class FalMediaProvider(MediaProvider):
    def __init__(self) -> None:
        super().__init__("fal")

    def capabilities(self) -> tuple[str, ...]:
        return (TEXT_TO_IMAGE,)

    @staticmethod
    def _api_key() -> str:
        return Settings.FAL_API_KEY or Settings.LTX_API_KEY

    def is_available(self) -> bool:
        return bool(self._api_key())

    def unavailable_reason(self) -> str:
        if self._api_key():
            return ""
        return "FAL_API_KEY not configured (LTX_API_KEY, also a fal.ai key, would work too) -- auth missing"

    def profiles(self) -> tuple[MediaModelProfile, ...]:
        available = self.is_available()
        return (
            MediaModelProfile(
                provider_id=self.provider_id, model_id=Settings.FAL_IMAGE_MODEL,
                capabilities=(TEXT_TO_IMAGE,), availability=available, auth_required=True,
                cost_class=self._cost_class(), free_tier=False, subscription_cli=False,
                local_or_remote="remote", quality_tier=78, speed_tier=90,
                supports_vertical_video=False, supports_image_conditioning=False,
                supports_duration_control=False, supports_seed=True, supports_audio=False,
                max_duration_seconds=None,
                notes="fal.ai-hosted FLUX.1-schnell (https://fal.ai/models/fal-ai/flux/schnell). "
                      "Second, independent text_to_image candidate alongside NVIDIA NIM.",
                unavailable_reason=self.unavailable_reason(),
            ),
        )

    @staticmethod
    def _cost_class() -> str:
        from src.providers.cost_optimizer import CostOptimizer
        return CostOptimizer.cost_class("fal")

    def generate_image(self, prompt: str, *, width: int = 1024, height: int = 1024,
                        seed: int = 0, model: str | None = None) -> MediaGenerationResult:
        model_id = model or Settings.FAL_IMAGE_MODEL
        if not self.is_available():
            return MediaGenerationResult(False, self.provider_id, model_id, TEXT_TO_IMAGE,
                                          error=self.unavailable_reason(), cost_class=self._cost_class())

        started = time.monotonic()
        response = None
        try:
            payload = {
                "prompt": prompt[:10000], "image_size": {"width": width, "height": height},
                "num_images": 1, "num_inference_steps": 4, "enable_safety_checker": True,
            }
            if seed:  # 0 means "no preference" in this codebase's convention -- let fal randomize
                payload["seed"] = seed
            response = requests.post(
                f"{Settings.FAL_BASE_URL}/{model_id}",
                headers={"Authorization": f"Key {self._api_key()}", "Content-Type": "application/json"},
                json=payload,
                timeout=(Settings.FAL_CONNECT_TIMEOUT_SECONDS, Settings.FAL_READ_TIMEOUT_SECONDS),
            )
            response.raise_for_status()
            data = response.json()
            images = data.get("images") or []
            if not images or not images[0].get("url"):
                return MediaGenerationResult(False, self.provider_id, model_id, TEXT_TO_IMAGE,
                                              error="fal image generation returned no image",
                                              duration_seconds=round(time.monotonic() - started, 2),
                                              cost_class=self._cost_class())
            url = images[0]["url"]
            content = self._download(url)
            return MediaGenerationResult(True, self.provider_id, model_id, TEXT_TO_IMAGE,
                                          content_bytes=content, content_url=url, seed_used=data.get("seed"),
                                          duration_seconds=round(time.monotonic() - started, 2),
                                          cost_class=self._cost_class())
        except requests.exceptions.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            reason = ("fal auth failed (invalid/expired key)" if status in (401, 403)
                      else "fal quota/rate limit reached" if status == 429
                      else f"fal HTTP error {status}")
            detail = self._safe_error_excerpt(error.response)
            if detail:
                reason = f"{reason} -- {detail}"
            return MediaGenerationResult(False, self.provider_id, model_id, TEXT_TO_IMAGE, error=reason,
                                          duration_seconds=round(time.monotonic() - started, 2),
                                          cost_class=self._cost_class())
        except requests.exceptions.Timeout as error:
            phase = "connect" if isinstance(error, requests.exceptions.ConnectTimeout) else "read"
            limit = (Settings.FAL_CONNECT_TIMEOUT_SECONDS if phase == "connect"
                     else Settings.FAL_READ_TIMEOUT_SECONDS)
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_IMAGE,
                error=f"fal request timed out ({phase} phase, limit {limit}s) -- not retried",
                duration_seconds=round(time.monotonic() - started, 2),
                cost_class=self._cost_class(),
            )
        except (requests.exceptions.RequestException, ValueError, KeyError) as error:
            reason = f"fal provider error: {error}"
            detail = self._safe_error_excerpt(response)
            if detail:
                reason = f"{reason} -- {detail}"
            return MediaGenerationResult(False, self.provider_id, model_id, TEXT_TO_IMAGE, error=reason,
                                          duration_seconds=round(time.monotonic() - started, 2),
                                          cost_class=self._cost_class())

    @staticmethod
    def _download(url: str) -> bytes:
        response = requests.get(url, timeout=(Settings.FAL_CONNECT_TIMEOUT_SECONDS, Settings.FAL_READ_TIMEOUT_SECONDS))
        response.raise_for_status()
        return response.content

    @staticmethod
    def _safe_error_excerpt(response: "requests.Response | None") -> str:
        """Short, secret-free excerpt of a fal error response body. Never
        touches request headers/Authorization/API key -- only reads the
        server's response, truncated."""
        if response is None:
            return ""
        try:
            body = response.json()
        except ValueError:
            return (response.text or "").strip()[:200]
        if isinstance(body, dict):
            detail = body.get("detail") or body.get("error") or body.get("message")
            if detail is not None:
                return str(detail)[:200]
        return str(body)[:200]
