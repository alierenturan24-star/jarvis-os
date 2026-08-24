from __future__ import annotations

import json

from src.control_center.service import ControlCenterService
from src.control_center.store import ControlCenterStore
from src.providers.provider_manager import ProviderManager


class _FakeProvider:
    def __init__(self, available: bool = True) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, model: str | None = None) -> str:
        return "ok"


class _FakeCeo:
    def __init__(self, provider_manager: ProviderManager) -> None:
        self.provider_manager = provider_manager


class _FakeJarvis:
    def __init__(self, provider_manager: ProviderManager) -> None:
        self.ceo = _FakeCeo(provider_manager)
        self.last_mission = None


class _FakeRuntime:
    BOOTING, SLEEPING, WORKING, STOPPED = "BOOTING", "SLEEPING", "WORKING", "STOPPED"

    def __init__(self, provider_manager: ProviderManager) -> None:
        self.state = self.SLEEPING
        self.jarvis = _FakeJarvis(provider_manager)


def _service(tmp_path, monkeypatch) -> ControlCenterService:
    monkeypatch.chdir(tmp_path)
    manager = ProviderManager()
    manager._providers = {
        "ollama": _FakeProvider(available=True),
        "gemini": _FakeProvider(available=True),
        "openai": _FakeProvider(available=False),
        "codex": _FakeProvider(available=False),
    }
    runtime = _FakeRuntime(manager)
    store = ControlCenterStore(tmp_path / "state.json")
    return ControlCenterService(runtime, store)


class TestProviderCostProjection:
    def test_each_row_carries_a_verified_cost_class(self, tmp_path, monkeypatch):
        service = _service(tmp_path, monkeypatch)
        rows = {row["name"]: row for row in service.providers()}

        assert rows["ollama"]["cost_class"] == "free"
        assert rows["gemini"]["cost_class"] == "free"
        assert rows["openai"]["cost_class"] == "paid"
        assert rows["codex"]["cost_class"] == "plan"

    def test_availability_is_still_projected_correctly(self, tmp_path, monkeypatch):
        service = _service(tmp_path, monkeypatch)
        rows = {row["name"]: row for row in service.providers()}

        assert rows["ollama"]["available"] is True
        assert rows["openai"]["available"] is False

    def test_no_secret_material_appears_in_the_projection(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "sk-super-secret-value-12345")
        service = _service(tmp_path, monkeypatch)

        dumped = json.dumps(service.providers())
        assert "sk-super-secret-value-12345" not in dumped
        assert "api_key" not in dumped.lower()
        assert "secret" not in dumped.lower()
