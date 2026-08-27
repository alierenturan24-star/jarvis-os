from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import requests

from src.config.settings import Settings
from src.media.capability_model import (
    IMAGE_TO_VIDEO, MediaGenerationResult, MediaModelProfile, TEXT_TO_VIDEO,
)
from src.providers.media_provider_base import MediaProvider

# Sprint: multi-provider media capability foundation -- LTX-Video.
#
# Two genuinely distinct capability paths, reported separately (never
# conflated):
#
#   LOCAL: would require a CUDA-capable GPU and locally-present model
#   weights. This machine reports Intel UHD graphics with no confirmed
#   CUDA/NVIDIA GPU -- JARVIS does NOT download large weights automatically
#   (explicit instruction) and does NOT claim local availability without
#   evidence. Detection is dependency-free (no torch/CUDA library added):
#   ``nvidia-smi`` presence is used as the GPU-presence signal, plus an
#   optional configured local weights directory.
#
#   REMOTE: LTX-2.5 is officially hosted on fal.ai (Lightricks partnership,
#   https://fal.ai/ltx-2.5). Contract re-verified 2026-08-26 directly
#   against fal's own model API-reference pages (the prior
#   fal-ai/ltx-2/... model ids in this file were stale):
#     model ids: lightricks/ltx-2.5/text-to-video/fast
#                lightricks/ltx-2.5/image-to-video/fast
#     Auth: Authorization: Key <key>  (fal.ai account-wide key)
#     Request (text-to-video): {"prompt": str, "duration": int|"auto",
#       "resolution": "1080p", "aspect_ratio": "9:16"|"16:9", "fps": 25,
#       "generate_audio": bool}
#     Request (image-to-video) adds: {"image_url": str}
#     Response (queue result): {"video": {"url": str, "content_type":
#       "video/mp4", "duration": float, "width": int, "height": int, ...}}
#
#   fal's own docs state this model uses the QUEUE workflow (submit ->
#   request_id -> poll status -> fetch result), not one long-held sync
#   request -- appropriate for a multi-second-to-minutes video generation.
#   See ``_generate`` below: bounded total deadline
#   (LTX_QUEUE_DEADLINE_SECONDS), bounded interval between polls
#   (LTX_POLL_INTERVAL_SECONDS), a clear non-crashing timeout result, and
#   NO automatic resubmission of the same (billable) request on timeout.
#
#   Opt-in only via LTX_API_KEY; unconfigured by default (no fake call).

_GPU_PROBE_TIMEOUT_SECONDS = 5


class LTXMediaProvider(MediaProvider):
    def __init__(self) -> None:
        super().__init__("ltx")

    def capabilities(self) -> tuple[str, ...]:
        return (TEXT_TO_VIDEO, IMAGE_TO_VIDEO)

    # --- local ---------------------------------------------------------

    @staticmethod
    def _gpu_detected() -> bool:
        nvidia_smi = shutil.which("nvidia-smi")
        if not nvidia_smi:
            return False
        try:
            result = subprocess.run([nvidia_smi], capture_output=True, timeout=_GPU_PROBE_TIMEOUT_SECONDS, check=False)
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def local_available(self) -> bool:
        return self._gpu_detected() and bool(Settings.LTX_LOCAL_WEIGHTS_DIR) \
            and Path(Settings.LTX_LOCAL_WEIGHTS_DIR).is_dir()

    def local_unavailable_reason(self) -> str:
        if not self._gpu_detected():
            return "no CUDA-capable GPU detected (nvidia-smi not found/failed) -- local hardware insufficient"
        if not Settings.LTX_LOCAL_WEIGHTS_DIR:
            return "LTX_LOCAL_WEIGHTS_DIR not configured -- no local weights; JARVIS does not auto-download them"
        return f"configured LTX_LOCAL_WEIGHTS_DIR does not exist: {Settings.LTX_LOCAL_WEIGHTS_DIR}"

    # --- remote ----------------------------------------------------------

    def remote_available(self) -> bool:
        return bool(Settings.LTX_API_KEY)

    def remote_unavailable_reason(self) -> str:
        if Settings.LTX_API_KEY:
            return ""
        return "LTX_API_KEY not configured -- remote/API LTX capability not activated"

    # --- MediaProvider contract -------------------------------------------

    def is_available(self) -> bool:
        return self.local_available() or self.remote_available()

    def unavailable_reason(self) -> str:
        if self.is_available():
            return ""
        return f"local: {self.local_unavailable_reason()}; remote: {self.remote_unavailable_reason()}"

    def profiles(self) -> tuple[MediaModelProfile, ...]:
        local_ok = self.local_available()
        remote_ok = self.remote_available()
        return (
            MediaModelProfile(
                provider_id=self.provider_id, model_id="ltx-2.5 (local)",
                capabilities=(TEXT_TO_VIDEO, IMAGE_TO_VIDEO), availability=local_ok, auth_required=False,
                cost_class="free", free_tier=False, subscription_cli=False, local_or_remote="local",
                quality_tier=75, speed_tier=60, supports_vertical_video=True, supports_image_conditioning=True,
                supports_duration_control=True, supports_seed=True, supports_audio=False,
                max_duration_seconds=20.0,
                notes="Requires a CUDA-capable GPU and locally-present weights; JARVIS never downloads "
                      "large model weights automatically.",
                unavailable_reason="" if local_ok else self.local_unavailable_reason(),
            ),
            # Two separate profiles below (not one profile claiming both
            # capabilities under a single model_id) -- text-to-video and
            # image-to-video are genuinely DIFFERENT fal-hosted model
            # endpoints/ids; a shared model_id would misreport which model
            # actually ran, and would prevent capability-scoped health
            # tracking (src.media.provider_selection.provider_health) from
            # meaning what it claims.
            MediaModelProfile(
                provider_id=self.provider_id, model_id=Settings.LTX_TEXT_TO_VIDEO_MODEL,
                capabilities=(TEXT_TO_VIDEO,), availability=remote_ok, auth_required=True,
                cost_class=self._cost_class(), free_tier=False, subscription_cli=False, local_or_remote="remote",
                quality_tier=82, speed_tier=55, supports_vertical_video=True, supports_image_conditioning=False,
                supports_duration_control=True, supports_seed=False, supports_audio=True,
                max_duration_seconds=20.0,
                notes="fal.ai-hosted LTX-2.5 text-to-video (https://fal.ai/ltx-2.5). Opt-in via LTX_API_KEY.",
                unavailable_reason="" if remote_ok else self.remote_unavailable_reason(),
            ),
            MediaModelProfile(
                provider_id=self.provider_id, model_id=Settings.LTX_IMAGE_TO_VIDEO_MODEL,
                capabilities=(IMAGE_TO_VIDEO,), availability=remote_ok, auth_required=True,
                cost_class=self._cost_class(), free_tier=False, subscription_cli=False, local_or_remote="remote",
                quality_tier=82, speed_tier=55, supports_vertical_video=True, supports_image_conditioning=True,
                supports_duration_control=True, supports_seed=False, supports_audio=True,
                max_duration_seconds=20.0,
                notes="fal.ai-hosted LTX-2.5 image-to-video (https://fal.ai/ltx-2.5). Opt-in via LTX_API_KEY.",
                unavailable_reason="" if remote_ok else self.remote_unavailable_reason(),
            ),
        )

    @staticmethod
    def _cost_class() -> str:
        from src.providers.cost_optimizer import CostOptimizer
        return CostOptimizer.cost_class("ltx")

    # --- generation --------------------------------------------------------

    def generate_video_from_text(self, prompt: str, *, duration_seconds: int | None = None,
                                  vertical: bool = True) -> MediaGenerationResult:
        return self._generate(TEXT_TO_VIDEO, Settings.LTX_TEXT_TO_VIDEO_MODEL,
                               {"prompt": prompt[:5000], "duration": duration_seconds or "auto",
                                "resolution": "1080p", "aspect_ratio": "9:16" if vertical else "16:9",
                                "fps": 25, "generate_audio": False})

    def generate_video_from_image(self, prompt: str, image_url: str, *,
                                   duration_seconds: int | None = None) -> MediaGenerationResult:
        return self._generate(IMAGE_TO_VIDEO, Settings.LTX_IMAGE_TO_VIDEO_MODEL,
                               {"prompt": prompt[:5000], "image_url": image_url,
                                "duration": duration_seconds or "auto", "generate_audio": False})

    @staticmethod
    def _headers() -> dict[str, str]:
        return {"Authorization": f"Key {Settings.LTX_API_KEY}", "Content-Type": "application/json"}

    @staticmethod
    def _call_timeout() -> tuple[float, float]:
        return (Settings.LTX_CONNECT_TIMEOUT_SECONDS, Settings.LTX_CALL_TIMEOUT_SECONDS)

    def _generate(self, capability: str, model_id: str, body: dict) -> MediaGenerationResult:
        """fal's documented queue workflow: submit -> request_id -> bounded
        status polling -> result. Never holds one HTTP request open for the
        full generation; never resubmits the SAME request after a timeout
        (one user request => at most one billable submit call)."""
        if not self.remote_available():
            return MediaGenerationResult(False, self.provider_id, model_id, capability,
                                          error=self.remote_unavailable_reason(), cost_class=self._cost_class())
        started = time.monotonic()
        response = None
        try:
            submit_response = requests.post(
                f"{Settings.LTX_QUEUE_BASE_URL}/{model_id}", headers=self._headers(),
                json=body, timeout=self._call_timeout(),
            )
            response = submit_response
            submit_response.raise_for_status()
            submit_data = submit_response.json()
            request_id = submit_data.get("request_id")
            if not request_id:
                return MediaGenerationResult(False, self.provider_id, model_id, capability,
                                              error="LTX queue submit did not return a request_id",
                                              duration_seconds=round(time.monotonic() - started, 2),
                                              cost_class=self._cost_class())
            status_url = submit_data.get("status_url") \
                or f"{Settings.LTX_QUEUE_BASE_URL}/{model_id}/requests/{request_id}/status"
            result_url = submit_data.get("response_url") \
                or f"{Settings.LTX_QUEUE_BASE_URL}/{model_id}/requests/{request_id}"

            deadline = started + Settings.LTX_QUEUE_DEADLINE_SECONDS
            status = ""
            while time.monotonic() < deadline:
                status_response = requests.get(status_url, headers=self._headers(), timeout=self._call_timeout())
                response = status_response
                status_response.raise_for_status()
                status_data = status_response.json()
                status = status_data.get("status", "")
                if status == "COMPLETED":
                    break
                if status_data.get("error"):
                    return MediaGenerationResult(False, self.provider_id, model_id, capability,
                                                  error=f"LTX generation failed: {status_data.get('error')}",
                                                  duration_seconds=round(time.monotonic() - started, 2),
                                                  cost_class=self._cost_class())
                time.sleep(Settings.LTX_POLL_INTERVAL_SECONDS)

            if status != "COMPLETED":
                return MediaGenerationResult(
                    False, self.provider_id, model_id, capability,
                    error=f"LTX generation timed out waiting in the fal queue (request_id={request_id}, "
                          f"deadline={Settings.LTX_QUEUE_DEADLINE_SECONDS}s) -- not resubmitted",
                    duration_seconds=round(time.monotonic() - started, 2), cost_class=self._cost_class())

            result_response = requests.get(result_url, headers=self._headers(), timeout=self._call_timeout())
            response = result_response
            result_response.raise_for_status()
            data = result_response.json()
            video = data.get("video") or {}
            url = video.get("url")
            if not url:
                return MediaGenerationResult(False, self.provider_id, model_id, capability,
                                              error="LTX response did not include a video URL",
                                              duration_seconds=round(time.monotonic() - started, 2),
                                              cost_class=self._cost_class())
            content = self._download(url)
            return MediaGenerationResult(True, self.provider_id, model_id, capability,
                                          content_bytes=content, content_url=url,
                                          duration_seconds=round(time.monotonic() - started, 2),
                                          cost_class=self._cost_class())
        except requests.exceptions.HTTPError as error:
            status_code = error.response.status_code if error.response is not None else None
            reason = ("LTX auth failed (invalid/expired key)" if status_code in (401, 403)
                      else "LTX quota/rate limit reached" if status_code == 429
                      else f"LTX HTTP error {status_code}")
            detail = self._safe_error_excerpt(error.response)
            if detail:
                reason = f"{reason} -- {detail}"
            return MediaGenerationResult(False, self.provider_id, model_id, capability, error=reason,
                                          duration_seconds=round(time.monotonic() - started, 2),
                                          cost_class=self._cost_class())
        except requests.exceptions.Timeout as error:
            phase = "connect" if isinstance(error, requests.exceptions.ConnectTimeout) else "read"
            return MediaGenerationResult(
                False, self.provider_id, model_id, capability,
                error=f"LTX request timed out ({phase} phase) -- not retried",
                duration_seconds=round(time.monotonic() - started, 2), cost_class=self._cost_class())
        except (requests.exceptions.RequestException, ValueError, KeyError) as error:
            reason = f"LTX sağlayıcı hatası: {error}"
            detail = self._safe_error_excerpt(response)
            if detail:
                reason = f"{reason} -- {detail}"
            return MediaGenerationResult(False, self.provider_id, model_id, capability, error=reason,
                                          duration_seconds=round(time.monotonic() - started, 2),
                                          cost_class=self._cost_class())

    @staticmethod
    def _download(url: str) -> bytes:
        response = requests.get(url, timeout=(Settings.LTX_CONNECT_TIMEOUT_SECONDS, Settings.LTX_CALL_TIMEOUT_SECONDS))
        response.raise_for_status()
        return response.content

    @staticmethod
    def _safe_error_excerpt(response: "requests.Response | None") -> str:
        """Short, secret-free excerpt of an LTX/fal error response body.
        Never touches request headers/Authorization/API key -- only reads
        the server's response, truncated."""
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
