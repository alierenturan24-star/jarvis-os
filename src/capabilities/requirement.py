from __future__ import annotations

from dataclasses import dataclass, field

from src.media.capability_model import (
    IMAGE_TO_VIDEO,
    TEXT_TO_IMAGE,
    TEXT_TO_VIDEO,
    THUMBNAIL_GENERATION,
    TTS,
    VIDEO_RENDER,
)
from src.mission.models import MissionType

# Fine-grained capability vocabulary the media-provider work (src.media.
# capability_model) does not cover: text/reasoning capabilities and the
# always-local "assemble the final file" step. Reused, not duplicated: the
# media capability strings above come straight from
# src.media.capability_model.MEDIA_CAPABILITIES -- this module only adds the
# non-media names.
WEB_RESEARCH = "web_research"
REASONING = "reasoning"
SCRIPT_GENERATION = "script_generation"
CODE_GENERATION = "code_generation"
# Local ffmpeg-based compositing (src.media.renderer) -- not a remote
# provider, always a candidate fallback for "produce a video from a still
# image" when no image_to_video/text_to_video provider is available.
DETERMINISTIC_VIDEO_RENDER = "deterministic_video_render"

REQUIRED = "REQUIRED"
OPTIONAL = "OPTIONAL"


@dataclass(frozen=True)
class CapabilityRequirement:
    """One capability a goal needs. ``alternatives`` is an OR of AND-groups:
    any one inner tuple, if every capability name in it resolves, satisfies
    the requirement. A requirement with a single single-name group behaves
    like a plain "needs capability X"."""

    name: str
    necessity: str  # REQUIRED | OPTIONAL
    alternatives: tuple[tuple[str, ...], ...]
    reason: str = ""


@dataclass(frozen=True)
class CapabilityPlan:
    requirements: tuple[CapabilityRequirement, ...] = field(default_factory=tuple)


# Declarative, mission-type-keyed table -- same style as
# src.mission.department.DEFAULT_DEPARTMENTS_BY_MISSION_TYPE and
# src.mission.recovery._DISCOVERY_FOCUS_BY_MISSION_TYPE. A mission type
# absent from this table simply gets no fine-grained requirements (honest
# "not modeled yet", not a fabricated guess) -- existing coarse
# Mission.required_capabilities/capability_gaps are untouched either way.
_REQUIREMENTS_BY_MISSION_TYPE: dict[MissionType, tuple[CapabilityRequirement, ...]] = {
    MissionType.RESEARCH: (
        CapabilityRequirement(WEB_RESEARCH, REQUIRED, ((WEB_RESEARCH,),)),
    ),
    MissionType.FINANCE: (
        CapabilityRequirement(WEB_RESEARCH, REQUIRED, ((WEB_RESEARCH,),)),
        CapabilityRequirement(REASONING, REQUIRED, ((REASONING,),)),
    ),
    MissionType.CODE: (
        CapabilityRequirement(CODE_GENERATION, REQUIRED, ((CODE_GENERATION,),)),
    ),
    MissionType.AI_DISCOVERY: (
        CapabilityRequirement(WEB_RESEARCH, REQUIRED, ((WEB_RESEARCH,),)),
    ),
    # YouTube/media production goals: a visual scene can come from a real
    # text-to-video model, OR a still image animated into video, OR (lowest
    # quality but always-local) a still image composited by the existing
    # deterministic renderer -- see src.media.renderer/production.py.
    MissionType.YOUTUBE: (
        CapabilityRequirement(WEB_RESEARCH, REQUIRED, ((WEB_RESEARCH,),)),
        CapabilityRequirement(SCRIPT_GENERATION, REQUIRED, ((SCRIPT_GENERATION,),)),
        CapabilityRequirement(
            "visual_scene_generation", REQUIRED,
            ((TEXT_TO_VIDEO,), (TEXT_TO_IMAGE, IMAGE_TO_VIDEO), (TEXT_TO_IMAGE, DETERMINISTIC_VIDEO_RENDER)),
        ),
        CapabilityRequirement(TTS, REQUIRED, ((TTS,),)),
        CapabilityRequirement(VIDEO_RENDER, REQUIRED, ((VIDEO_RENDER,),)),
        CapabilityRequirement(THUMBNAIL_GENERATION, OPTIONAL, ((THUMBNAIL_GENERATION,), (TEXT_TO_IMAGE,))),
    ),
    MissionType.MEDIA: (
        CapabilityRequirement(SCRIPT_GENERATION, REQUIRED, ((SCRIPT_GENERATION,),)),
        CapabilityRequirement(
            "visual_scene_generation", REQUIRED,
            ((TEXT_TO_VIDEO,), (TEXT_TO_IMAGE, IMAGE_TO_VIDEO), (TEXT_TO_IMAGE, DETERMINISTIC_VIDEO_RENDER)),
        ),
        CapabilityRequirement(TTS, OPTIONAL, ((TTS,),)),
        CapabilityRequirement(VIDEO_RENDER, REQUIRED, ((VIDEO_RENDER,),)),
        CapabilityRequirement(THUMBNAIL_GENERATION, OPTIONAL, ((THUMBNAIL_GENERATION,), (TEXT_TO_IMAGE,))),
    ),
}


def plan_capability_requirements(
    mission_type: MissionType, departments: tuple[str, ...], goal_text: str = "",
) -> tuple[CapabilityRequirement, ...]:
    """Generic requirement decomposition for a goal, keyed by the mission
    type/department selection the existing classifier already computed --
    not a per-goal hardcode (no "Swiss Insider" special case anywhere
    here)."""

    return _REQUIREMENTS_BY_MISSION_TYPE.get(mission_type, ())
