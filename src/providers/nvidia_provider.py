from __future__ import annotations

import base64
import time

import requests

from src.config.settings import Settings
from src.media.capability_model import MediaGenerationResult, MediaModelProfile, TEXT_TO_IMAGE
from src.providers.media_provider_base import MediaProvider

# Sprint: multi-provider media capability foundation -- NVIDIA NIM.
#
# Real, documented API contract (verified against NVIDIA's own NIM for
# Visual Generative AI reference, https://docs.nvidia.com/nim/visual-genai/,
# and the build.nvidia.com model page for black-forest-labs/flux.1-schnell):
#
#   POST {NVIDIA_BASE_URL}/{model}          e.g. https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell
#   Headers: Authorization: Bearer <key>, Content-Type: application/json, Accept: application/json
#   Body:    {"prompt": str, "width": int, "height": int, "seed": int, "steps": int,
#             "samples": 1, "mode": "base", "cfg_scale": 0}
#   Response: {"artifacts": [{"base64": "<jpeg-or-png base64>", "finishReason": "SUCCESS", "seed": int}]}
#
# This module implements ONLY text_to_image (the capability with a verified
# request/response contract). NVIDIA NIM also hosts video-capable models,
# but this pass does not claim text_to_video/image_to_video for NVIDIA --
# "Do NOT assume every NVIDIA-hosted model can generate image/video"
# (explicit instruction). Adding a verified video contract is future work,
# not guessed here.

_SUPPORTED_WIDTHS = (768, 832, 896, 960, 1024, 1088, 1152, 1216, 1280, 1344)


class NvidiaMediaProvider(MediaProvider):
    def __init__(self) -> None:
        super().__init__("nvidia")

    def capabilities(self) -> tuple[str, ...]:
        return (TEXT_TO_IMAGE,)

    def is_available(self) -> bool:
        return bool(Settings.NVIDIA_API_KEY)

    def unavailable_reason(self) -> str:
        if Settings.NVIDIA_API_KEY:
            return ""
        return "NVIDIA_API_KEY not configured -- auth missing"

    def profiles(self) -> tuple[MediaModelProfile, ...]:
        available = self.is_available()
        return (
            MediaModelProfile(
                provider_id=self.provider_id, model_id=Settings.NVIDIA_IMAGE_MODEL,
                capabilities=(TEXT_TO_IMAGE,), availability=available, auth_required=True,
                cost_class=self._cost_class(), free_tier=False, subscription_cli=False,
                local_or_remote="remote", quality_tier=80, speed_tier=85,
                supports_vertical_video=False, supports_image_conditioning=False,
                supports_duration_control=False, supports_seed=True, supports_audio=False,
                max_duration_seconds=None,
                notes="NVIDIA NIM hosted image generation (OpenAI-compatible genai endpoint). "
                      "1024x1024-class stills only in this integration; no video capability claimed.",
                unavailable_reason=self.unavailable_reason(),
            ),
        )

    @staticmethod
    def _cost_class() -> str:
        from src.providers.cost_optimizer import CostOptimizer
        return CostOptimizer.cost_class("nvidia")

    def generate_image(self, prompt: str, *, width: int = 1024, height: int = 1024,
                        seed: int = 0, model: str | None = None) -> MediaGenerationResult:
        model_id = model or Settings.NVIDIA_IMAGE_MODEL
        if not self.is_available():
            return MediaGenerationResult(False, self.provider_id, model_id, TEXT_TO_IMAGE,
                                          error=self.unavailable_reason(), cost_class=self._cost_class())

        width = min(_SUPPORTED_WIDTHS, key=lambda candidate: abs(candidate - width))
        height = min(_SUPPORTED_WIDTHS, key=lambda candidate: abs(candidate - height))
        started = time.monotonic()
        response = None
        try:
            response = requests.post(
                f"{Settings.NVIDIA_BASE_URL}/{model_id}",
                headers={"Authorization": f"Bearer {Settings.NVIDIA_API_KEY}",
                         "Content-Type": "application/json", "Accept": "application/json"},
                json={"prompt": prompt[:10000], "width": width, "height": height, "seed": seed,
                      "steps": 4, "samples": 1, "mode": "base", "cfg_scale": 0},
                timeout=(Settings.NVIDIA_CONNECT_TIMEOUT_SECONDS, Settings.NVIDIA_READ_TIMEOUT_SECONDS),
            )
            response.raise_for_status()
            data = response.json()
            artifacts = data.get("artifacts") or []
            if not artifacts or artifacts[0].get("finishReason") != "SUCCESS":
                reason = artifacts[0].get("finishReason") if artifacts else "empty response"
                return MediaGenerationResult(False, self.provider_id, model_id, TEXT_TO_IMAGE,
                                              error=f"NVIDIA image generation did not succeed: {reason}",
                                              duration_seconds=round(time.monotonic() - started, 2),
                                              cost_class=self._cost_class())
            content = base64.b64decode(artifacts[0]["base64"])
            return MediaGenerationResult(True, self.provider_id, model_id, TEXT_TO_IMAGE,
                                          content_bytes=content, seed_used=artifacts[0].get("seed"),
                                          duration_seconds=round(time.monotonic() - started, 2),
                                          cost_class=self._cost_class())
        except requests.exceptions.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            reason = ("NVIDIA auth failed (invalid/expired key, or key lacks access to this model)"
                      if status in (401, 403)
                      else "NVIDIA quota/rate limit reached" if status == 429
                      else f"NVIDIA HTTP error {status}")
            detail = self._safe_error_excerpt(error.response)
            if detail:
                reason = f"{reason} -- {detail}"
            return MediaGenerationResult(False, self.provider_id, model_id, TEXT_TO_IMAGE, error=reason,
                                          duration_seconds=round(time.monotonic() - started, 2),
                                          cost_class=self._cost_class())
        except requests.exceptions.Timeout as error:
            phase = "connect" if isinstance(error, requests.exceptions.ConnectTimeout) else "read"
            limit = (Settings.NVIDIA_CONNECT_TIMEOUT_SECONDS if phase == "connect"
                     else Settings.NVIDIA_READ_TIMEOUT_SECONDS)
            return MediaGenerationResult(
                False, self.provider_id, model_id, TEXT_TO_IMAGE,
                error=f"NVIDIA request timed out ({phase} phase, limit {limit}s) -- not retried",
                duration_seconds=round(time.monotonic() - started, 2),
                cost_class=self._cost_class(),
            )
        except (requests.exceptions.RequestException, ValueError, KeyError) as error:
            reason = f"NVIDIA sağlayıcı hatası: {error}"
            detail = self._safe_error_excerpt(response)
            if detail:
                reason = f"{reason} -- {detail}"
            return MediaGenerationResult(False, self.provider_id, model_id, TEXT_TO_IMAGE,
                                          error=reason,
                                          duration_seconds=round(time.monotonic() - started, 2),
                                          cost_class=self._cost_class())

    @staticmethod
    def _safe_error_excerpt(response: "requests.Response | None") -> str:
        """Short, secret-free excerpt of an NVIDIA error response body.

        Never touches request headers/Authorization/API key -- only reads
        the server's response. Truncated so a runaway HTML error page can't
        blow up logs/results."""
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
