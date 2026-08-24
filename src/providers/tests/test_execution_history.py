from __future__ import annotations

from src.providers.execution_history import ProviderExecutionHistory


def _history(tmp_path, monkeypatch) -> ProviderExecutionHistory:
    monkeypatch.chdir(tmp_path)
    return ProviderExecutionHistory()


class TestRecordAndRecent:
    def test_empty_history_returns_empty_list(self, tmp_path, monkeypatch):
        history = _history(tmp_path, monkeypatch)
        assert history.recent() == []

    def test_record_appends_an_entry(self, tmp_path, monkeypatch):
        history = _history(tmp_path, monkeypatch)
        history.record(task_type="research", provider="ollama", success=True, fallback_used=False, duration_seconds=1.5)

        recent = history.recent()
        assert len(recent) == 1
        assert recent[0]["provider"] == "ollama"
        assert recent[0]["task_type"] == "research"
        assert recent[0]["success"] is True

    def test_recent_returns_newest_first(self, tmp_path, monkeypatch):
        history = _history(tmp_path, monkeypatch)
        history.record(task_type="research", provider="ollama", success=True, fallback_used=False, duration_seconds=1.0)
        history.record(task_type="finance", provider="aiml", success=False, fallback_used=True, duration_seconds=2.0)

        recent = history.recent()
        assert recent[0]["provider"] == "aiml"
        assert recent[1]["provider"] == "ollama"

    def test_recent_respects_limit(self, tmp_path, monkeypatch):
        history = _history(tmp_path, monkeypatch)
        for _ in range(5):
            history.record(task_type="research", provider="ollama", success=True, fallback_used=False, duration_seconds=1.0)
        assert len(history.recent(limit=2)) == 2

    def test_history_survives_a_new_instance_reading_the_same_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ProviderExecutionHistory().record(
            task_type="research", provider="ollama", success=True, fallback_used=False, duration_seconds=1.0,
        )
        second = ProviderExecutionHistory()
        assert len(second.recent()) == 1

    def test_entries_are_capped_at_max_entries(self, tmp_path, monkeypatch):
        import src.providers.execution_history as module
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(module, "MAX_ENTRIES", 3)

        history = module.ProviderExecutionHistory()
        for i in range(5):
            history.record(task_type="research", provider=f"p{i}", success=True, fallback_used=False, duration_seconds=1.0)

        assert len(history.recent(limit=10)) == 3
        # En yeni 3 kayıt tutulmalı (p2, p3, p4) -- en eski (p0, p1) düşmeli.
        providers = {entry["provider"] for entry in history.recent(limit=10)}
        assert providers == {"p2", "p3", "p4"}


class TestCostClass:
    def test_cost_class_is_omitted_when_not_supplied(self, tmp_path, monkeypatch):
        history = _history(tmp_path, monkeypatch)
        history.record(task_type="research", provider="ollama", success=True, fallback_used=False, duration_seconds=1.0)
        assert "cost_class" not in history.recent()[0]

    def test_cost_class_is_recorded_when_supplied(self, tmp_path, monkeypatch):
        history = _history(tmp_path, monkeypatch)
        history.record(
            task_type="research", provider="gemini", success=True, fallback_used=False,
            duration_seconds=1.0, cost_class="free",
        )
        assert history.recent()[0]["cost_class"] == "free"


class TestSuccessRate:
    def test_no_data_returns_none_not_a_fabricated_number(self, tmp_path, monkeypatch):
        history = _history(tmp_path, monkeypatch)
        assert history.success_rate("ollama") is None

    def test_success_rate_computed_correctly(self, tmp_path, monkeypatch):
        history = _history(tmp_path, monkeypatch)
        history.record(task_type="research", provider="ollama", success=True, fallback_used=False, duration_seconds=1.0)
        history.record(task_type="research", provider="ollama", success=True, fallback_used=False, duration_seconds=1.0)
        history.record(task_type="research", provider="ollama", success=False, fallback_used=False, duration_seconds=1.0)

        assert history.success_rate("ollama") == 66.7

    def test_success_rate_can_be_narrowed_by_task_type(self, tmp_path, monkeypatch):
        history = _history(tmp_path, monkeypatch)
        history.record(task_type="research", provider="ollama", success=True, fallback_used=False, duration_seconds=1.0)
        history.record(task_type="finance_analysis", provider="ollama", success=False, fallback_used=False, duration_seconds=1.0)

        assert history.success_rate("ollama", task_type="research") == 100.0
        assert history.success_rate("ollama", task_type="finance_analysis") == 0.0
