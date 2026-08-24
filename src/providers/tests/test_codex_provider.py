from __future__ import annotations

import subprocess

from src.mission.failure_classification import FailureClass
from src.providers.codex_provider import CodexProvider, CodexWorker, RESOURCE_TYPE


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["codex.cmd", "exec"], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def _available(monkeypatch):
    monkeypatch.setattr(
        "src.providers.codex_provider.shutil.which",
        lambda name: r"C:\fake\codex.cmd" if name == "codex.cmd" else None,
    )


class TestA_CliAvailable:
    def test_cmd_resolution_and_availability(self, monkeypatch):
        _available(monkeypatch)
        assert CodexWorker().is_available() is True


class TestB_Success:
    def test_non_interactive_output_returns_to_provider(self, monkeypatch):
        _available(monkeypatch)
        monkeypatch.setattr(
            "src.providers.codex_provider.subprocess.run",
            lambda *args, **kwargs: _completed(stdout="Gerçek Codex cevabı."),
        )
        provider = CodexProvider()
        assert provider.generate("prompt") == "Gerçek Codex cevabı."
        assert provider.last_result.success is True
        assert provider.last_result.resource_type == RESOURCE_TYPE


class TestC_CliMissing:
    def test_missing_is_canonical_and_does_not_crash(self, monkeypatch):
        monkeypatch.setattr("src.providers.codex_provider.shutil.which", lambda name: None)
        result = CodexWorker().run("prompt")
        assert result.success is False
        assert result.failure_class == FailureClass.PROVIDER_UNAVAILABLE


class TestD_Timeout:
    def test_timeout_is_canonical(self, monkeypatch):
        _available(monkeypatch)

        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

        monkeypatch.setattr("src.providers.codex_provider.subprocess.run", timeout)
        result = CodexWorker(timeout_seconds=1).run("prompt")
        assert result.success is False
        assert result.failure_class == FailureClass.TIMEOUT


class TestE_QuotaAndN_FalseSuccess:
    def test_zero_exit_usage_limit_is_not_success(self, monkeypatch):
        _available(monkeypatch)
        monkeypatch.setattr(
            "src.providers.codex_provider.subprocess.run",
            lambda *args, **kwargs: _completed(stdout="usage limit reached"),
        )
        result = CodexWorker().run("prompt")
        assert result.success is False
        assert result.failure_class == FailureClass.QUOTA_EXHAUSTED

    def test_success_log_mentioning_limit_does_not_poison_final_output(self, monkeypatch):
        _available(monkeypatch)
        monkeypatch.setattr(
            "src.providers.codex_provider.subprocess.run",
            lambda *args, **kwargs: _completed(
                stdout="Gerçek repository analizi.",
                stderr="tool log: source contains usage limit marker",
            ),
        )
        result = CodexWorker().run("prompt")
        assert result.success is True


class TestF_WorkingDirectoryAndG_CommandSafety:
    def test_safe_command_and_repository_cwd(self, tmp_path, monkeypatch):
        captured = {}
        _available(monkeypatch)

        def run(command, **kwargs):
            captured.update(command=command, kwargs=kwargs)
            return _completed(stdout="ok")

        monkeypatch.setattr("src.providers.codex_provider.subprocess.run", run)
        CodexWorker(cwd=tmp_path).run("prompt")
        command = captured["command"]
        assert command[1] == "exec"
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert captured["kwargs"]["cwd"] == str(tmp_path)
        assert captured["kwargs"]["shell"] is False
        assert not any("bypass" in arg or "danger" in arg for arg in command)


class TestProcessFailure:
    def test_nonzero_exit_is_provider_failure(self, monkeypatch):
        _available(monkeypatch)
        monkeypatch.setattr(
            "src.providers.codex_provider.subprocess.run",
            lambda *args, **kwargs: _completed(returncode=2, stderr="process failed"),
        )
        result = CodexWorker().run("prompt")
        assert result.success is False
        assert result.exit_code == 2
        assert result.failure_class == FailureClass.PROVIDER_UNAVAILABLE
