from __future__ import annotations

from src.media.capability_model import IMAGE_TO_VIDEO, TEXT_TO_IMAGE, TEXT_TO_VIDEO, MediaModelProfile
from src.media.provider_selection import provider_health, rank_available_providers, select_media_provider
from src.providers.execution_history import ProviderExecutionHistory
from src.providers.fal_provider import FalMediaProvider
from src.providers.ltx_provider import LTXMediaProvider
from src.providers.media_provider_base import MediaProvider
from src.providers.nvidia_provider import NvidiaMediaProvider


class _FakeProvider(MediaProvider):
    """Deterministic stand-in used to exercise ranking logic without any
    real network dependency -- capability match/availability/ranking are
    exercised against controlled profiles, independent of whether a real
    NVIDIA/LTX key happens to be configured in this environment."""

    def __init__(self, provider_id: str, profile: MediaModelProfile):
        super().__init__(provider_id)
        self._profile = profile

    def capabilities(self):
        return self._profile.capabilities

    def is_available(self):
        return self._profile.availability

    def unavailable_reason(self):
        return self._profile.unavailable_reason

    def profiles(self):
        return (self._profile,)

    def generate_image(self, prompt, **kwargs):
        raise NotImplementedError


def _profile(**overrides) -> MediaModelProfile:
    base = dict(provider_id="fake", model_id="fake-model", capabilities=(TEXT_TO_IMAGE,),
                availability=True, auth_required=True, cost_class="paid", free_tier=False,
                subscription_cli=False, local_or_remote="remote", quality_tier=70, speed_tier=70)
    base.update(overrides)
    return MediaModelProfile(**base)


def _empty_history(tmp_path, monkeypatch) -> ProviderExecutionHistory:
    monkeypatch.chdir(tmp_path)
    return ProviderExecutionHistory()


# A: a media task requiring text_to_image only selects providers that
# advertise text_to_image.
def test_text_to_image_task_never_selects_video_only_provider(tmp_path, monkeypatch):
    history = _empty_history(tmp_path, monkeypatch)
    image_provider = _FakeProvider("img", _profile(provider_id="img", capabilities=(TEXT_TO_IMAGE,)))
    video_provider = _FakeProvider("vid", _profile(provider_id="vid", capabilities=(TEXT_TO_VIDEO,)))
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (image_provider, video_provider))

    result = select_media_provider(TEXT_TO_IMAGE, history=history)

    assert result.selected is not None
    assert result.selected.provider_id == "img"


# B: a media task requiring image_to_video only selects compatible providers.
def test_image_to_video_task_only_selects_compatible_providers(tmp_path, monkeypatch):
    history = _empty_history(tmp_path, monkeypatch)
    image_provider = _FakeProvider("img", _profile(provider_id="img", capabilities=(TEXT_TO_IMAGE,)))
    i2v_provider = _FakeProvider("i2v", _profile(provider_id="i2v", capabilities=(IMAGE_TO_VIDEO,)))
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (image_provider, i2v_provider))

    result = select_media_provider(IMAGE_TO_VIDEO, history=history)

    assert result.selected is not None
    assert result.selected.provider_id == "i2v"


# F: multiple compatible providers are ranked rather than hardcoded (both
# support the capability; the cheaper/free one wins when quality is equal).
def test_multiple_compatible_providers_are_ranked_not_hardcoded(tmp_path, monkeypatch):
    history = _empty_history(tmp_path, monkeypatch)
    cheap = _FakeProvider("cheap", _profile(provider_id="cheap", cost_class="free", quality_tier=70))
    costly = _FakeProvider("costly", _profile(provider_id="costly", cost_class="paid", quality_tier=70))
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (costly, cheap))

    result = select_media_provider(TEXT_TO_IMAGE, history=history)

    assert result.selected.provider_id == "cheap"


# G: free/free-tier/local/subscription-included option is preferred when
# quality constraints are satisfied.
def test_free_option_preferred_when_quality_sufficient(tmp_path, monkeypatch):
    history = _empty_history(tmp_path, monkeypatch)
    free = _FakeProvider("free", _profile(provider_id="free", cost_class="free", quality_tier=75))
    paid = _FakeProvider("paid", _profile(provider_id="paid", cost_class="paid", quality_tier=95))
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (paid, free))

    result = select_media_provider(TEXT_TO_IMAGE, quality_required=False, history=history)

    assert result.selected.provider_id == "free"


# H: higher-quality provider can beat cheaper provider when task quality
# requirements require it.
def test_higher_quality_provider_wins_when_quality_required(tmp_path, monkeypatch):
    history = _empty_history(tmp_path, monkeypatch)
    free = _FakeProvider("free", _profile(provider_id="free", cost_class="free", quality_tier=75))
    paid = _FakeProvider("paid", _profile(provider_id="paid", cost_class="paid", quality_tier=95))
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (free, paid))

    result = select_media_provider(TEXT_TO_IMAGE, quality_required=True, history=history)

    assert result.selected.provider_id == "paid"


# K: all compatible providers unavailable -> CAPABILITY_GAP (selection
# returns no selected provider, with every candidate + reason recorded).
def test_all_unavailable_returns_gap_with_evidence(tmp_path, monkeypatch):
    history = _empty_history(tmp_path, monkeypatch)
    unavailable_a = _FakeProvider("a", _profile(provider_id="a", availability=False,
                                                 unavailable_reason="auth missing"))
    unavailable_b = _FakeProvider("b", _profile(provider_id="b", availability=False,
                                                 unavailable_reason="quota exhausted"))
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (unavailable_a, unavailable_b))

    result = select_media_provider(TEXT_TO_IMAGE, history=history)

    assert result.gap is True
    assert result.selected is None
    reasons = [c.reason for c in result.candidates_considered]
    assert any("auth missing" in r for r in reasons)
    assert any("quota exhausted" in r for r in reasons)


def test_rank_available_providers_orders_full_eligible_list(tmp_path, monkeypatch):
    history = _empty_history(tmp_path, monkeypatch)
    free = _FakeProvider("free", _profile(provider_id="free", cost_class="free", quality_tier=60))
    paid = _FakeProvider("paid", _profile(provider_id="paid", cost_class="paid", quality_tier=90))
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (paid, free))

    ranked, considered = rank_available_providers(TEXT_TO_IMAGE, history=history)

    assert [profile.provider_id for profile, _ in ranked] == ["free", "paid"]
    assert len(considered) == 2


# Sanity: the real NVIDIA/fal/LTX providers this foundation ships are
# actually registered and reachable through the same selection path (no
# separate, undiscoverable registry).
def test_real_providers_are_registered_for_selection():
    from src.media.provider_selection import _PROVIDERS
    ids = {p.provider_id for p in _PROVIDERS}
    assert "nvidia" in ids
    assert "fal" in ids
    assert "ltx" in ids
    assert any(isinstance(p, NvidiaMediaProvider) for p in _PROVIDERS)
    assert any(isinstance(p, FalMediaProvider) for p in _PROVIDERS)
    assert any(isinstance(p, LTXMediaProvider) for p in _PROVIDERS)


# J: two genuinely available, equally-healthy providers (e.g. NVIDIA + fal
# both configured) are ranked dynamically by the existing policy dimensions
# (cost/quality/speed), never hard-coded to always prefer one by name.
def test_two_available_providers_are_ranked_dynamically_not_hardcoded(tmp_path, monkeypatch):
    history = _empty_history(tmp_path, monkeypatch)
    provider_x = _FakeProvider("x", _profile(provider_id="x", cost_class="paid", quality_tier=80))
    provider_y = _FakeProvider("y", _profile(provider_id="y", cost_class="free", quality_tier=80))
    # Registration order deliberately does NOT match the expected winner
    # (y, the cheaper one) -- proves the selector, not list order, decides.
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (provider_x, provider_y))

    result = select_media_provider(TEXT_TO_IMAGE, history=history)

    assert result.selected.provider_id == "y"


# K: recent consecutive failures for a provider/capability cause a
# healthy compatible provider to win, even when the failing one would
# otherwise rank first on cost/quality alone.
def test_recent_failures_cause_healthy_provider_to_win(tmp_path, monkeypatch):
    history = _empty_history(tmp_path, monkeypatch)
    flaky = _FakeProvider("flaky", _profile(provider_id="flaky", cost_class="free", quality_tier=95))
    steady = _FakeProvider("steady", _profile(provider_id="steady", cost_class="paid", quality_tier=60))
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (flaky, steady))

    for _ in range(3):
        history.record(task_type=TEXT_TO_IMAGE, provider="flaky", success=False,
                        fallback_used=False, duration_seconds=1.0, cost_class="free")

    health = provider_health("flaky", TEXT_TO_IMAGE, history)
    assert health.status == "COOLDOWN"

    result = select_media_provider(TEXT_TO_IMAGE, history=history)
    assert result.selected.provider_id == "steady"
    # CAPABILITY_GAP evidence must explain WHY the cheaper/higher-quality
    # candidate was passed over, not silently omit it.
    flaky_reason = next(c.reason for c in result.candidates_considered if c.profile.provider_id == "flaky")
    assert "recently unhealthy" in flaky_reason


# L: a subsequent real success for the previously-failing provider restores
# its ranking immediately -- never a permanent blacklist.
def test_future_success_restores_provider_ranking(tmp_path, monkeypatch):
    history = _empty_history(tmp_path, monkeypatch)
    flaky = _FakeProvider("flaky", _profile(provider_id="flaky", cost_class="free", quality_tier=95))
    steady = _FakeProvider("steady", _profile(provider_id="steady", cost_class="paid", quality_tier=60))
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (flaky, steady))

    for _ in range(3):
        history.record(task_type=TEXT_TO_IMAGE, provider="flaky", success=False,
                        fallback_used=False, duration_seconds=1.0, cost_class="free")
    assert select_media_provider(TEXT_TO_IMAGE, history=history).selected.provider_id == "steady"

    history.record(task_type=TEXT_TO_IMAGE, provider="flaky", success=True,
                    fallback_used=False, duration_seconds=1.0, cost_class="free")

    health = provider_health("flaky", TEXT_TO_IMAGE, history)
    assert health.status == "HEALTHY"
    result = select_media_provider(TEXT_TO_IMAGE, history=history)
    assert result.selected.provider_id == "flaky"


# A provider in cooldown that is the ONLY compatible candidate must remain
# selectable -- cooldown deprioritizes, it never manufactures a false
# CAPABILITY_GAP.
def test_cooldown_provider_remains_selectable_when_it_is_the_only_option(tmp_path, monkeypatch):
    history = _empty_history(tmp_path, monkeypatch)
    only = _FakeProvider("only", _profile(provider_id="only"))
    monkeypatch.setattr("src.media.provider_selection._PROVIDERS", (only,))

    for _ in range(3):
        history.record(task_type=TEXT_TO_IMAGE, provider="only", success=False,
                        fallback_used=False, duration_seconds=1.0, cost_class="paid")

    result = select_media_provider(TEXT_TO_IMAGE, history=history)
    assert result.gap is False
    assert result.selected.provider_id == "only"
