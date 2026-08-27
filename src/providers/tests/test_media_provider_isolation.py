from __future__ import annotations

from src.providers.cost_optimizer import PLAN_CLI_PROVIDERS, TASK_COST_PROFILES, TASK_CODING
from src.providers.provider_manager import ProviderManager, TASK_TYPE_PROVIDERS

# P: existing Claude Code/Codex coding routing (and every other text task
# route) must remain unchanged by the multi-provider media capability
# foundation. NVIDIA/LTX are media (image/video) providers with a different
# contract (generate_image()/generate_video_from_*(), not generate(prompt)
# -> str) -- registering them into ProviderManager._providers would make
# ordinary chat/research/coding calls eligible to try them as a text
# fallback once profile candidates are exhausted (see
# ProviderManager._route_candidates' registry_candidates loop). This test
# pins the deliberate separation described in
# src.providers.media_provider_base's module docstring.


def test_media_providers_are_not_registered_in_provider_manager():
    manager = ProviderManager()
    assert "nvidia" not in manager.names()
    assert "fal" not in manager.names()
    assert "ltx" not in manager.names()


def test_media_providers_are_not_in_any_text_task_routing_table():
    assert "nvidia" not in TASK_TYPE_PROVIDERS.values()
    assert "fal" not in TASK_TYPE_PROVIDERS.values()
    assert "ltx" not in TASK_TYPE_PROVIDERS.values()
    assert "nvidia" not in PLAN_CLI_PROVIDERS
    assert "fal" not in PLAN_CLI_PROVIDERS
    assert "ltx" not in PLAN_CLI_PROVIDERS
    for profile in TASK_COST_PROFILES.values():
        assert profile.priority_provider not in {"nvidia", "fal", "ltx"}
        assert profile.fallback_provider not in {"nvidia", "fal", "ltx"}


def test_coding_task_profile_still_prefers_codex_then_claude_code():
    coding = TASK_COST_PROFILES[TASK_CODING]
    assert coding.priority_provider == "codex"
    assert coding.fallback_provider == "claude_code"
