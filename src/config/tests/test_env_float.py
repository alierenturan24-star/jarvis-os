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


class TestE_NvidiaTimeoutSettingsAreBoundedByConstruction:
    """2026-08-26: a real hosted flux.1-schnell call exceeded the old flat,
    unbounded ``NVIDIA_TIMEOUT = int(os.getenv(...))``. Replaced with two
    _env_float-bounded settings -- same fail-closed convention as
    CLAUDE_CODE_TIMEOUT_SECONDS above, never a parallel parsing scheme."""

    def test_connect_timeout_resolved_setting_is_within_its_own_bounds(self):
        assert 3.0 <= Settings.NVIDIA_CONNECT_TIMEOUT_SECONDS <= 30.0

    def test_read_timeout_resolved_setting_is_within_its_own_bounds(self):
        assert 20.0 <= Settings.NVIDIA_READ_TIMEOUT_SECONDS <= 300.0

    def test_read_timeout_default_is_more_realistic_than_the_old_60s_default(self):
        assert Settings.NVIDIA_READ_TIMEOUT_SECONDS > 60.0

    def test_malformed_connect_timeout_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_CONNECT_TIMEOUT_SECONDS", "not-a-number")
        assert _env_float("NVIDIA_CONNECT_TIMEOUT_SECONDS", 10.0, minimum=3.0, maximum=30.0) == 10.0

    def test_out_of_range_connect_timeout_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_CONNECT_TIMEOUT_SECONDS", "999")
        assert _env_float("NVIDIA_CONNECT_TIMEOUT_SECONDS", 10.0, minimum=3.0, maximum=30.0) == 10.0

    def test_malformed_read_timeout_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_READ_TIMEOUT_SECONDS", "inf")
        assert _env_float("NVIDIA_READ_TIMEOUT_SECONDS", 120.0, minimum=20.0, maximum=300.0) == 120.0

    def test_out_of_range_read_timeout_env_falls_back_to_default_never_unbounded(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_READ_TIMEOUT_SECONDS", "999999999")
        assert _env_float("NVIDIA_READ_TIMEOUT_SECONDS", 120.0, minimum=20.0, maximum=300.0) == 120.0

    def test_valid_read_timeout_env_within_bounds_is_honored(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_READ_TIMEOUT_SECONDS", "90")
        assert _env_float("NVIDIA_READ_TIMEOUT_SECONDS", 120.0, minimum=20.0, maximum=300.0) == 90.0
