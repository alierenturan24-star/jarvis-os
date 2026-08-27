from __future__ import annotations

from abc import ABC, abstractmethod

from src.media.capability_model import MediaModelProfile

# Sprint: multi-provider media capability foundation. Deliberately NOT a
# subclass of src.providers.base_provider.BaseProvider and deliberately NOT
# registered into src.providers.provider_manager.ProviderManager._providers:
# that manager's candidate chains (_route_candidates) iterate every
# registered provider as a generic TEXT completion fallback for ANY task
# type once profile candidates are exhausted. A media provider's
# generate_image()/generate_video() calls are not interchangeable with that
# text contract -- registering one there would silently make ordinary
# chat/research/coding calls eligible to try, e.g., an image-generation
# endpoint as a text fallback. This is a sibling family with the SAME
# pattern (provider_id, is_available(), Settings-driven env auth) rather
# than a second ProviderManager: selection lives in
# src.media.provider_selection (one small module, no new router), execution
# history/cost classification are the EXISTING ProviderExecutionHistory/
# CostOptimizer, reused by string-keyed task_type/provider_id values.


class MediaProvider(ABC):
    """Common contract for providers that generate media (image/video/audio),
    as opposed to BaseProvider's text-completion contract."""

    provider_id: str

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id

    @abstractmethod
    def capabilities(self) -> tuple[str, ...]:
        """Capabilities this provider genuinely implements in THIS codebase
        -- never a capability merely because the remote host advertises it
        elsewhere."""
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        """True only when genuinely callable right now (auth configured,
        and for local capabilities, hardware/weights present)."""
        raise NotImplementedError

    @abstractmethod
    def unavailable_reason(self) -> str:
        """Human-readable, secret-free reason when ``is_available()`` is
        False. Empty string when available."""
        raise NotImplementedError

    @abstractmethod
    def profiles(self) -> tuple[MediaModelProfile, ...]:
        """One MediaModelProfile per model/mode this provider exposes."""
        raise NotImplementedError
