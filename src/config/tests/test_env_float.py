from __future__ import annotations

from src.config.settings import Settings, _env_float


class TestA_MissingOrEmptyFallsBackToDefault:
    def test_unset_env_var_returns_default(self, monkeypatch):
        monkeypatch.delenv("SOME_TIMEOUT_VAR", raising=False)
        assert _env_float("SOME_TIMEOUT_VAR", 180.0) == 180.0

    def test_empty_string_returns_default(self, monkeypatch):
        monkeypatch.setenv("SOME_TIMEOUT_VAR", "   ")
        assert _env_float("SOME_TIMEOUT_VAR", 180.0) == 180.0


class TestB_ValidValueIsConfigurable:
    def test_valid_value_within_bounds_is_used(self, monkeypatch):
        monkeypatch.setenv("SOME_TIMEOUT_VAR", "90")
        assert _env_float("SOME_TIMEOUT_VAR", 180.0, minimum=30.0, maximum=600.0) == 90.0

    def test_value_with_surrounding_whitespace_is_accepted(self, monkeypatch):
        monkeypatch.setenv("SOME_TIMEOUT_VAR", "  120.5  ")
        assert _env_float("SOME_TIMEOUT_VAR", 180.0) == 120.5


class TestC_MalformedOrUnsafeValueFailsClosedToDefault:
    """Requirement 9.C: malformed/unsafe timeout configuration must fail
    safely to the default -- never raise, never produce an unbounded wait."""

    def test_non_numeric_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("SOME_TIMEOUT_VAR", "not-a-number")
        assert _env_float("SOME_TIMEOUT_VAR", 180.0, minimum=30.0, maximum=600.0) == 180.0

    def test_below_minimum_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("SOME_TIMEOUT_VAR", "1")
        assert _env_float("SOME_TIMEOUT_VAR", 180.0, minimum=30.0, maximum=600.0) == 180.0

    def test_above_maximum_falls_back_to_default_never_unbounded(self, monkeypatch):
        monkeypatch.setenv("SOME_TIMEOUT_VAR", "999999999")
        assert _env_float("SOME_TIMEOUT_VAR", 180.0, minimum=30.0, maximum=600.0) == 180.0

    def test_infinity_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("SOME_TIMEOUT_VAR", "inf")
        assert _env_float("SOME_TIMEOUT_VAR", 180.0, minimum=30.0, maximum=600.0) == 180.0

    def test_nan_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("SOME_TIMEOUT_VAR", "nan")
        assert _env_float("SOME_TIMEOUT_VAR", 180.0, minimum=30.0, maximum=600.0) == 180.0

    def test_never_raises_regardless_of_garbage_input(self, monkeypatch):
        for garbage in ("", "abc", "-5", "1e999", "0x10", "None", ";rm -rf /"):
            monkeypatch.setenv("SOME_TIMEOUT_VAR", garbage)
            _env_float("SOME_TIMEOUT_VAR", 180.0, minimum=30.0, maximum=600.0)  # must not raise


class TestD_ClaudeCodeTimeoutSettingIsBoundedByConstruction:
    def test_resolved_setting_is_within_its_own_documented_bounds(self):
        assert 30.0 <= Settings.CLAUDE_CODE_TIMEOUT_SECONDS <= 600.0

    def test_resolved_setting_is_more_realistic_than_the_old_60s_default(self):
        assert Settings.CLAUDE_CODE_TIMEOUT_SECONDS > 60.0
