"""Deterministic boundaries for mission tests.

Mission tests exercise orchestration, not the workstation's installed CLIs,
API keys, network, or Ollama daemon.  Individual tests replace providers with
their own fakes when availability is part of the scenario.
"""

import pytest

from src.providers.provider_manager import ProviderManager


@pytest.fixture(autouse=True)
def deterministic_provider_registry(monkeypatch, tmp_path):
    original_init = ProviderManager.__init__

    def init(manager):
        original_init(manager)
        for provider in manager._providers.values():
            monkeypatch.setattr(provider, "is_available", lambda: False)

    monkeypatch.setattr(ProviderManager, "__init__", init)
    # Mission orchestration tests must not launch a workstation ffmpeg process
    # against an artifact left by a previous run. Dedicated media quality tests
    # cover the real probe boundary separately.
    monkeypatch.setattr(
        "src.media.quality._measure_local_body_motion",
        lambda artifact, evidence, ffmpeg: (False, None),
    )
    # Never inspect persisted artifacts from an earlier workstation run. Tests
    # which create an artifact in their own tmp_path still exercise the real
    # quality validator.
    from pathlib import Path
    from src.media import quality
    original_validate = quality.validate_media_goal_artifact

    def validate_current_test_artifact(path, goal=""):
        try:
            Path(path).resolve().relative_to(tmp_path.resolve())
        except (OSError, ValueError):
            return quality.MediaArtifactQuality(False, False, False, ("artifact outside test sandbox",))
        return original_validate(path, goal)

    monkeypatch.setattr(quality, "validate_media_goal_artifact", validate_current_test_artifact)
