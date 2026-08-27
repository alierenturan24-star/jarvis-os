from __future__ import annotations

from src.capabilities import resolution
from src.capabilities.requirement import (
    CODE_GENERATION,
    DETERMINISTIC_VIDEO_RENDER,
    OPTIONAL,
    REQUIRED,
    CapabilityRequirement,
    plan_capability_requirements,
)
from src.capabilities.resolution import CapabilityResolution, resolve_capability_requirement
from src.media.capability_model import IMAGE_TO_VIDEO, TEXT_TO_IMAGE, TEXT_TO_VIDEO, THUMBNAIL_GENERATION
from src.mission.models import MissionType


def test_visual_scene_generation_has_three_alternative_groups():
    requirements = plan_capability_requirements(MissionType.YOUTUBE, ("media",), "produce a short")
    visual = next(r for r in requirements if r.name == "visual_scene_generation")
    assert visual.necessity == REQUIRED
    assert visual.alternatives == (
        (TEXT_TO_VIDEO,),
        (TEXT_TO_IMAGE, IMAGE_TO_VIDEO),
        (TEXT_TO_IMAGE, DETERMINISTIC_VIDEO_RENDER),
    )


def test_thumbnail_generation_is_optional_others_required():
    requirements = plan_capability_requirements(MissionType.YOUTUBE, ("media",), "produce a short")
    thumbnail = next(r for r in requirements if r.name == THUMBNAIL_GENERATION)
    script = next(r for r in requirements if r.name == "script_generation")
    assert thumbnail.necessity == OPTIONAL
    assert script.necessity == REQUIRED


def test_mission_type_without_table_entry_returns_empty():
    assert plan_capability_requirements(MissionType.SECURITY, ("security",), "audit") == ()


def test_code_mission_requires_code_generation():
    requirements = plan_capability_requirements(MissionType.CODE, ("coding",), "fix a bug")
    assert requirements == (
        CapabilityRequirement(CODE_GENERATION, REQUIRED, ((CODE_GENERATION,),)),
    )


def test_alternative_group_selection_picks_first_fully_resolved_group(monkeypatch):
    """Phase 11-A: alternatives are tried in declared order and only the
    first group whose EVERY member resolves is used -- a failing earlier
    group must not leak into the chosen resolution."""

    def fake_resolve(name, **_kwargs):
        if name in (TEXT_TO_IMAGE, IMAGE_TO_VIDEO):
            return CapabilityResolution(capability=name, status=resolution.READY, resolved_by=f"provider/{name}")
        return CapabilityResolution(capability=name, status=resolution.CAPABILITY_GAP)

    monkeypatch.setattr(resolution, "resolve_capability_name", fake_resolve)

    requirement = CapabilityRequirement(
        "visual_scene_generation", REQUIRED,
        ((TEXT_TO_VIDEO,), (TEXT_TO_IMAGE, IMAGE_TO_VIDEO), (TEXT_TO_IMAGE, DETERMINISTIC_VIDEO_RENDER)),
    )
    result = resolve_capability_requirement(requirement)

    assert result.status == resolution.READY
    assert f"provider/{TEXT_TO_IMAGE}" in result.resolved_by and f"provider/{IMAGE_TO_VIDEO}" in result.resolved_by
    assert TEXT_TO_VIDEO not in result.resolved_by
