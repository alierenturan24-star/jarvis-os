from __future__ import annotations

from dataclasses import dataclass, field

# Sprint: multi-provider media capability foundation. JARVIS's existing
# capability system (src.capabilities.capability.Capability) tracks whether
# JARVIS should ADOPT a new external tool/repository into itself -- a
# completely different question from "which already-integrated provider can
# genuinely perform text_to_image/image_to_video/tts right now". This module
# is the truthful vocabulary for the second question; it does not replace or
# extend the self-evolution capability system.
#
# Reused, not duplicated: CostOptimizer.cost_class()/FREE_TIER_PROVIDERS/
# PLAN_CLI_PROVIDERS (src.providers.cost_optimizer) remain the single source
# of cost classification -- media providers register themselves into those
# same tables (see nvidia_provider.py/ltx_provider.py) instead of a second
# cost model. ProviderExecutionHistory (src.providers.execution_history)
# remains the single execution-history store -- media task types
# ("text_to_image", "image_to_video", ...) are just additional task_type
# values recorded through the SAME class.

TEXT_GENERATION = "text_generation"
RESEARCH = "research"
TEXT_TO_IMAGE = "text_to_image"
IMAGE_TO_IMAGE = "image_to_image"
TEXT_TO_VIDEO = "text_to_video"
IMAGE_TO_VIDEO = "image_to_video"
VIDEO_TO_VIDEO = "video_to_video"
MOTION_GENERATION = "motion_generation"
TTS = "tts"
SPEECH_GENERATION = "speech_generation"
THUMBNAIL_GENERATION = "thumbnail_generation"
VIDEO_RENDER = "video_render"

MEDIA_CAPABILITIES = (
    TEXT_TO_IMAGE, IMAGE_TO_IMAGE, TEXT_TO_VIDEO, IMAGE_TO_VIDEO, VIDEO_TO_VIDEO,
    MOTION_GENERATION, TTS, SPEECH_GENERATION, THUMBNAIL_GENERATION, VIDEO_RENDER,
)


@dataclass(frozen=True)
class MediaModelProfile:
    """Structured, truthful facts about one provider/model pairing.

    ``availability``/``auth_required`` are always computed live from actual
    provider state (env/config presence, not a cached guess) by whichever
    provider builds this profile -- see ``NvidiaMediaProvider.profile()``/
    ``LTXMediaProvider.profiles()``. Never hand-authored as a static claim.
    """

    provider_id: str
    model_id: str
    capabilities: tuple[str, ...]
    availability: bool
    auth_required: bool
    cost_class: str  # "free" | "plan" | "paid" | "unknown" -- CostOptimizer.cost_class()
    free_tier: bool
    subscription_cli: bool
    local_or_remote: str  # "local" | "remote"
    quality_tier: int  # 0-100, relative -- not a fabricated absolute benchmark
    speed_tier: int  # 0-100, relative
    supports_vertical_video: bool = False
    supports_image_conditioning: bool = False
    supports_duration_control: bool = False
    supports_seed: bool = False
    supports_audio: bool = False
    max_duration_seconds: float | None = None
    notes: str = ""
    unavailable_reason: str = ""


@dataclass(frozen=True)
class MediaGenerationResult:
    """Result of one real generation call -- never fabricated on failure."""

    success: bool
    provider_id: str
    model_id: str
    capability: str
    content_bytes: bytes | None = None
    content_url: str = ""
    seed_used: int | None = None
    duration_seconds: float | None = None
    error: str = ""
    cost_class: str = "unknown"


@dataclass(frozen=True)
class SceneProvenance:
    """Safe, credential-free provenance for one generated scene/artifact --
    persisted into the production manifest (Phase 7 requirement). Reuses the
    existing manifest dict pattern (GeneralProductionBuilder writes plain
    dicts); this dataclass exists only to keep the field set consistent and
    documented in one place."""

    scene_id: str
    capability: str
    provider: str
    model: str
    generation_type: str  # e.g. "text_to_image", "legacy_authored_compositor"
    output_path: str
    success: bool
    fallback_used: bool = False
    cost_class: str = "unknown"
    input_reference: str = ""
    duration_seconds: float | None = None
    quality_evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "scene_id": self.scene_id, "capability": self.capability,
            "provider": self.provider, "model": self.model,
            "generation_type": self.generation_type, "output_path": self.output_path,
            "success": self.success, "fallback_used": self.fallback_used,
            "cost_class": self.cost_class, "input_reference": self.input_reference,
            "duration_seconds": self.duration_seconds, "quality_evidence": dict(self.quality_evidence),
        }
