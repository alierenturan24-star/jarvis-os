from __future__ import annotations

import base64
import time

import requests

from src.config.settings import Settings
from src.media.capability_model import MediaGenerationResult, MediaModelProfile, TEXT_TO_IMAGE
from src.providers.media_provider_base import MediaProvider

# Sprint: multi-provider media capability foundation -- AIML API
# (aimlapi.com) as a text_to_image source.
#
# Real, documented API contract (verified directly against AIML API's own
# docs, https://docs.aimlapi.com/api-references/image-models/flux/
# flux-schnell -- and the sibling flux-dev/flux-pro pages, which confirm
# every FLUX image model shares this SAME endpoint; only "model" differs):
#
#   POST {AIML_BASE_URL}/images/generations   e.g. https://api.aimlapi.com/v1/images/generations
#   Headers: Authorization: Bearer <key>, Content-Type: application/json
#   Body:    {"model": str, "prompt": str (<=4000 chars),
#             "image_size": {"width": int, "height": int} (multiples of 32,
#             64-1536), "num_images": 1, "enable_safety_checker": true,
#             "seed": int (optional)}
#   Response: the docs page's own CONCRETE example (fal-backed FLUX models)
#             is {"images": [{"url": str, "width": int, "height": int,
#             "content_type": str}], "seed": int, "has_nsfw_concepts":
#             [bool], "prompt": str} -- matching this codebase's existing
#             FalMediaProvider response shape (AIML proxies fal-hosted
#             FLUX). The SAME docs page ALSO shows a generic, seemingly
#             auto-generated OpenAI-style envelope ({"data": [{"url"|
#             "b64_json": str}], "meta": {"usage": {"credits_used": ...}}})
#             for the SAME model -- ambiguous/inconsistent documentation,
#             not resolved by guessing. Both shapes are handled
#             defensively below (never assumed without checking).
#
# Errors (AIML's own documented 4xx table,
# https://docs.aimlapi.com/errors-and-messages/errors-with-status-code-4xx):
#   401 = missing/invalid API key, 403 = authenticated but no credits
#   (billing/quota), 429 = rate limit.
#
# This module implements ONLY text_to_image -- no text_to_video/
# image_to_video claimed for AIML in this pass (that would need its own
# verified contract, not guessed here). The existing text-completion
# ``AIMLProvider`` (src/providers/aiml_provider.py, POST .../chat/
# completions) is completely untouched -- this is a SEPARATE class
# following the ``MediaProvider`` contract (see media_provider_base.py's
# module docstring for why media providers are never registered into
# ProviderManager's text-completion fallback chain: an image endpoint must
# never become eligible as a text-completion fallback for an unrelated
# chat/research/coding call).
#
# Single flat request timeout (``Settings.AIML_TIMEOUT``, already used by
# the text provider) -- this is a synchronous image endpoint (unlike
# LTX-2.5's async fal queue workflow for video), so no polling loop is
# needed at all: at most one POST and, if the response is URL-based, one
# bounded GET download. No retries.

_MIN_DIMENSION, _MAX_DIMENSION = 64, 1536


def _round_to_multiple_of_32(value: int) -> int:
    return max(_MIN_DIMENSION, min(_MAX_DIMENSION, round(value / 32) * 32))


class AIMLMediaProvider(MediaProvider):
    def __init__(self) -> None:
        super().__init__("aiml")

    def capabilities(self) -> tuple[str, ...]:
        return (TEXT_TO_IMAGE,)

    def is_available(self) -> bool:
        return bool(Settings.AIML_API_KEY)

    def unavailable_reason(self) -> str:
        if Settings.AIML_API_KEY:
            return ""
        return "AIML_API_KEY not configured -- auth missing"

    def profiles(self) -> tuple[MediaModelProfile, ...]:
        available = self.is_available()
        return (
            MediaModelProfile(
                provider_id=self.provider_id, model_id=Settings.AIML_IMAGE_MODEL,
                capabilities=(TEXT_TO_IMAGE,), availability=available, auth_required=True,
                cost_class=self._cost_class(), free_tier=False, subscription_cli=False,
                local_or_remote="remote", quality_tier=78, speed_tier=88,
                supports_vertical_video=False, supports_image_conditioning=False,
                supports_duration_control=False, supports_seed=True, supports_audio=False,
                max_duration_seconds=None,
                notes="AIML API (aimlapi.com) hosted FLUX image generation "
                      "(https://docs.aimlapi.com/api-references/image-models/flux/). "
                      "Paid per-call -- existing free/local-preferred ranking policy "
                      "(src.media.provider_selection) decides whether it is actually used.",
                unavailable_reason=self.unavailable_reason(),
            ),
        )

    @staticmethod
    def _cost_class() -> str:
        from src.providers.cost_optimizer import CostOptimizer
        return CostOptimizer.cost_class("aiml")

    def generate_image(self, prompt: str, *, width: int = 1024, height: int = 768,
                        seed: int = 0, model: str | None = None) -> MediaGenerationResult:
        model_id = model or Settings.AIML_IMAGE_MODEL
        if not self.is_available():
            return MediaGenerationResult(False, self.provider_id, model_id, TEXT_TO_IMAGE,
                                          error=self.unavailable_reason(), cost_class=self._cost_class())

        payload = {
            "model": model_id,
            "prompt": prompt[:4000],
            "image_size": {
                "width": _round_to_multiple_of_32(width),
                "height": _round_to_multiple_of_32(height),
            },
            "num_images": 1,
            "enable_safety_checker": True,
        }
        if seed:  # 0 means "no preference" in this codebase's convention -- let AIML randomize
            payload["seed"] = seed

        started = time.monotonic()
        response = None
        try:
            response = requests.post(
                f"{Settings.AIML_BASE_URL}/images/generations",
                headers={"Authorization": f"Bearer {Settings.AIML_API_KEY}", "Content-Type": "application/json"},
                json=payload,
                timeout=Settings.AIML_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            # Handles both documented response shapes (see module docstring)
            # -- never assumes which one a live call would actually return.
            images = data.get("images") or data.get("data") or []
            first = images[0] if images else None
            if not isinstance(first, dict):
                return MediaGenerationResult(False, self.provider_id, model_id, TEXT_TO_IMAGE,
                                              error="AIML image generation returned no usable image entry",
                                              duration_seconds=round(time.monotonic() - started, 2),
                                              cost_class=self._cost_class())

            url = str(first.get("url") or "")
            content: bytes | None = None
            if url:
                content = self._download(url)
            elif first.get("b64_json"):
                content = base64.b64decode(first["b64_json"])

            if not content:
                return MediaGenerationResult(False, self.provider_id, model_id, TEXT_TO_IMAGE,
                                              error="AIML image response did not include a usable image "
                                                    "(no url or b64_json field)",
                                              duration_seconds=round(time.monotonic() - started, 2),
                                              cost_class=self._cost_class())

            return MediaGenerationResult(True, self.provider_id, model_id, TEXT_TO_IMAGE,
                                          content_bytes=content, content_url=url, seed_used=data.get("seed"),
                                          duration_seconds=round(time.monotonic() - started, 2),
                                          cost_class=self._cost_class())
        except requests.exceptions.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            reason = ("AIML auth failed (invalid/expired key)" if status == 401
                      else "AIML quota/billing failure (no credits)" if status == 403
                      else "AIML rate limit reached" if status == 429
                      else f"AIML HTTP error {status}")
            detail = self._safe_error_excerpt(error.response)
            if detail:
                reason = f"{reason} -- {detail}"
            return MediaGenerationResult(False, self.provider_id, model_id, TEXT_TO_IMAGE, error=reason,
                                          duration_seconds=round(time.monotonic() - started, 2),
                                          cost_class=self._cost_class())
        except requests.exceptions.Timeout:
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_IMAGE,
                error=f"AIML request timed out (limit {Settings.AIML_TIMEOUT}s) -- not retried",
                duration_seconds=round(time.monotonic() - started, 2), cost_class=self._cost_class())
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError) as error:
            reason = f"AIML sağlayıcı hatası: {error}"
            detail = self._safe_error_excerpt(response)
            if detail:
                reason = f"{reason} -- {detail}"
            return MediaGenerationResult(False, self.provider_id, model_id, TEXT_TO_IMAGE, error=reason,
                                          duration_seconds=round(time.monotonic() - started, 2),
                                          cost_class=self._cost_class())

    @staticmethod
    def _download(url: str) -> bytes:
        response = requests.get(url, timeout=Settings.AIML_TIMEOUT)
        response.raise_for_status()
        return response.content

    @staticmethod
    def _safe_error_excerpt(response: "requests.Response | None") -> str:
        """Short, secret-free excerpt of an AIML error response body. Never
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
