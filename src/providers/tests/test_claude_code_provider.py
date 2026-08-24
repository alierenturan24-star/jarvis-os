from __future__ import annotations

import json
import subprocess

from src.mission.failure_classification import FailureClass
from src.providers.claude_code_provider import ClaudeCodeProvider, ClaudeCodeWorker


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr)


def _success_json(result_text="Gerçek Claude Code cevabı.", session_id="sess-123", cost=0.02):
    return json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "result": result_text, "session_id": session_id, "total_cost_usd": cost,
    })


def _error_json(result_text="", subtype="error_during_execution", session_id="sess-err"):
    return json.dumps({
        "type": "result", "subtype": subtype, "is_error": True,
        "result": result_text, "session_id": session_id, "total_cost_usd": 0.001,
    })


class TestA_CliAvailable:
    def test_worker_available_when_executable_resolves(self, monkeypatch):
        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        worker = ClaudeCodeWorker()
        assert worker.is_available() is True

    def test_provider_available_delegates_to_worker(self, monkeypatch):
        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        provider = ClaudeCodeProvider()
        assert provider.is_available() is True


class TestB_Success:
    def test_run_returns_real_output_on_success(self, monkeypatch):
        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr(
            "src.providers.claude_code_provider.subprocess.run",
            lambda *a, **kw: _completed(stdout=_success_json()),
        )
        worker = ClaudeCodeWorker()
        result = worker.run("test prompt")

        assert result.success is True
        assert result.output == "Gerçek Claude Code cevabı."
        assert result.session_id == "sess-123"
        assert result.cost_usd == 0.02
        assert result.failure_class == FailureClass.UNKNOWN

    def test_provider_generate_returns_output_to_jarvis(self, monkeypatch):
        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr(
            "src.providers.claude_code_provider.subprocess.run",
            lambda *a, **kw: _completed(stdout=_success_json("Kod incelemesi tamamlandı.")),
        )
        provider = ClaudeCodeProvider()
        output = provider.generate("test prompt")

        assert output == "Kod incelemesi tamamlandı."
        assert provider.last_result.success is True


class TestC_Quota:
    def test_usage_limit_text_classified_as_quota_exhausted_not_false_success(self, monkeypatch):
        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr(
            "src.providers.claude_code_provider.subprocess.run",
            lambda *a, **kw: _completed(
                stdout=_error_json("You have reached your usage limit for this session."),
            ),
        )
        worker = ClaudeCodeWorker()
        result = worker.run("test prompt")

        assert result.success is False
        assert result.failure_class == FailureClass.QUOTA_EXHAUSTED

    def test_rate_limit_text_classified_as_recoverable(self, monkeypatch):
        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr(
            "src.providers.claude_code_provider.subprocess.run",
            lambda *a, **kw: _completed(stdout=_error_json("429 rate limit exceeded, please retry later.")),
        )
        worker = ClaudeCodeWorker()
        result = worker.run("test prompt")

        assert result.success is False
        assert result.failure_class in (FailureClass.QUOTA_EXHAUSTED, FailureClass.RATE_LIMIT)


class TestD_Timeout:
    def test_timeout_expired_maps_to_timeout_and_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )

        def _raise_timeout(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=110.0)

        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _raise_timeout)
        worker = ClaudeCodeWorker()

        result = worker.run("test prompt")  # çökmemeli

        assert result.success is False
        assert result.failure_class == FailureClass.TIMEOUT
        assert "zaman aşımına uğradı" in result.output


class TestE_CliMissing:
    def test_missing_executable_maps_to_provider_unavailable_no_crash(self, monkeypatch):
        monkeypatch.setattr("src.providers.claude_code_provider.shutil.which", lambda name: None)
        worker = ClaudeCodeWorker()

        result = worker.run("test prompt")  # çökmemeli, subprocess hiç çağrılmamalı

        assert result.success is False
        assert result.failure_class == FailureClass.PROVIDER_UNAVAILABLE
        assert "bulunamadı" in result.output

    def test_provider_is_available_false_when_cli_missing(self, monkeypatch):
        monkeypatch.setattr("src.providers.claude_code_provider.shutil.which", lambda name: None)
        assert ClaudeCodeProvider().is_available() is False


class TestK_WorkingDirectory:
    def test_subprocess_runs_with_project_root_cwd_by_default(self, monkeypatch):
        from src.config.settings import PROJECT_ROOT

        captured = {}

        def _fake_run(command, **kwargs):
            captured["cwd"] = kwargs.get("cwd")
            return _completed(stdout=_success_json())

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        ClaudeCodeWorker().run("test prompt")

        assert captured["cwd"] == str(PROJECT_ROOT)

    def test_explicit_cwd_override_is_honored(self, monkeypatch):
        captured = {}

        def _fake_run(command, **kwargs):
            captured["cwd"] = kwargs.get("cwd")
            return _completed(stdout=_success_json())

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        from pathlib import Path
        custom = Path("C:/some/other/project")
        ClaudeCodeWorker(cwd=custom).run("test prompt")

        assert captured["cwd"] == str(custom)


class TestL_CommandSafety:
    def test_shell_is_never_true(self, monkeypatch):
        captured = {}

        def _fake_run(command, **kwargs):
            captured["kwargs"] = kwargs
            captured["command"] = command
            return _completed(stdout=_success_json())

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        ClaudeCodeWorker().run("test prompt")

        assert captured["kwargs"].get("shell") is not True
        assert isinstance(captured["command"], list)

    def test_dangerous_permission_flags_never_present(self, monkeypatch):
        captured = {}

        def _fake_run(command, **kwargs):
            captured["command"] = command
            return _completed(stdout=_success_json())

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        ClaudeCodeWorker().run("test prompt")

        joined = " ".join(captured["command"])
        assert "--dangerously-skip-permissions" not in joined
        assert "--allow-dangerously-skip-permissions" not in joined

    def test_default_permission_mode_is_safe_plan_mode(self, monkeypatch):
        captured = {}

        def _fake_run(command, **kwargs):
            captured["command"] = command
            return _completed(stdout=_success_json())

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        ClaudeCodeWorker().run("test prompt")

        command = captured["command"]
        idx = command.index("--permission-mode")
        assert command[idx + 1] == "plan"
        assert command[idx + 1] not in ("bypassPermissions", "acceptEdits", "dontAsk")

    def test_timeout_is_bounded_under_coding_department_outer_timeout(self):
        # Sprint 45: "coding" now gets its OWN wider outer budget (derived
        # from claude_code + codex's inner timeouts, see
        # department_orchestrator.CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS)
        # instead of the shared DEPARTMENT_TASK_TIMEOUT_SECONDS -- the inner
        # timeout must stay bounded under THAT budget, with room left for a
        # subsequent codex fallback attempt in the same task.
        from src.mission.department_orchestrator import CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS
        from src.providers.codex_provider import DEFAULT_TIMEOUT_SECONDS as CODEX_TIMEOUT_SECONDS

        worker = ClaudeCodeWorker()
        assert worker.timeout_seconds < CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS
        assert worker.timeout_seconds + CODEX_TIMEOUT_SECONDS < CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS


class TestR_ConfigurableBoundedTimeout:
    """Requirement A/B: the module default is no longer fixed to an
    unrealistically short 60s, and is safely configurable (bounded)."""

    def test_default_timeout_is_no_longer_the_old_unrealistic_60s(self):
        from src.providers.claude_code_provider import DEFAULT_TIMEOUT_SECONDS

        assert DEFAULT_TIMEOUT_SECONDS > 60.0

    def test_default_timeout_stays_finite_and_bounded(self):
        from src.providers.claude_code_provider import DEFAULT_TIMEOUT_SECONDS

        assert 30.0 <= DEFAULT_TIMEOUT_SECONDS <= 600.0

    def test_explicit_timeout_override_is_honored_by_the_subprocess_call(self, monkeypatch):
        captured = {}

        def _fake_run(command, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return _completed(stdout=_success_json())

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        ClaudeCodeWorker(timeout_seconds=222.0).run("test prompt")

        assert captured["timeout"] == 222.0


class TestEnvironmentIsolation:
    """Sprint 44 CANLI testte bulunan GERÇEK hata: ``subprocess.run``
    varsayılan olarak TÜM ebeveyn ortam değişkenlerini miras alır. JARVIS'in
    ``.env``'i (``anthropic_provider.py`` -- AYRI, HTTP tabanlı Anthropic API
    sağlayıcısı -- için) ``ANTHROPIC_MODEL=claude-sonnet-4`` tanımlıyor;
    bu, Claude Code CLI'ye SIZINCA CLI'nin kendi model seçimini bozup HER
    çağrıda 404 ile başarısız oluyordu. Bu test o düzeltmeyi kilitler."""

    def test_jarvis_anthropic_env_vars_are_stripped_from_subprocess_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-key-should-not-leak")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://fake.example.com")
        monkeypatch.setenv("SOME_OTHER_VAR", "kept")

        captured = {}

        def _fake_run(command, **kwargs):
            captured["env"] = kwargs.get("env")
            return _completed(stdout=_success_json())

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        ClaudeCodeWorker().run("test prompt")

        env = captured["env"]
        assert env is not None
        assert "ANTHROPIC_MODEL" not in env
        assert "ANTHROPIC_API_KEY" not in env
        assert "ANTHROPIC_BASE_URL" not in env
        assert env.get("SOME_OTHER_VAR") == "kept"  # ilgisiz değişkenler KORUNUR


class TestM_EditWorkingDirectoryBoundary:
    """Mode B (repo-edit): ``run_edit`` bir GERÇEKTEN var olan dizin
    gerektirir ve iyi bilinen tehlikeli köklerde ASLA çalışmaz (test E)."""

    def test_missing_directory_is_rejected_without_invoking_cli(self, monkeypatch, tmp_path):
        called = {"run": False}
        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )

        def _fake_run(*a, **kw):
            called["run"] = True
            return _completed(stdout=_success_json())

        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        result = ClaudeCodeWorker().run_edit("test prompt", cwd=tmp_path / "does_not_exist")

        assert result.success is False
        assert called["run"] is False

    def test_home_directory_root_is_rejected(self, monkeypatch):
        from pathlib import Path

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        called = {"run": False}
        monkeypatch.setattr(
            "src.providers.claude_code_provider.subprocess.run",
            lambda *a, **kw: called.__setitem__("run", True) or _completed(stdout=_success_json()),
        )

        result = ClaudeCodeWorker().run_edit("test prompt", cwd=Path.home())

        assert result.success is False
        assert called["run"] is False

    def test_valid_project_subdirectory_is_accepted(self, monkeypatch, tmp_path):
        captured = {}

        def _fake_run(command, **kwargs):
            captured["cwd"] = kwargs.get("cwd")
            return _completed(stdout=_success_json())

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        result = ClaudeCodeWorker().run_edit("test prompt", cwd=tmp_path)

        assert result.success is True
        assert captured["cwd"] == str(tmp_path.resolve())


class TestN_EditAllowedToolsIsAnAllowlist:
    """``run_edit`` Bash/WebFetch/Task/MCP'yi KATEGORİK olarak dışarıda
    bırakan bir İZİN LİSTESİ kullanır -- destructive git action'lar CLI
    alt-sürecinden mimari olarak İMKANSIZDIR (güvenlik madde 3/8)."""

    def test_command_uses_accept_edits_and_allowlisted_tools_only(self, monkeypatch, tmp_path):
        captured = {}

        def _fake_run(command, **kwargs):
            if command and command[0] == "git":
                return _completed(returncode=0, stdout="")
            captured["command"] = command
            return _completed(stdout=_success_json())

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        ClaudeCodeWorker().run_edit("test prompt", cwd=tmp_path)

        command = captured["command"]
        joined = " ".join(command)
        assert "--dangerously-skip-permissions" not in joined
        assert "--allow-dangerously-skip-permissions" not in joined
        idx = command.index("--permission-mode")
        assert command[idx + 1] == "acceptEdits"
        tools_idx = command.index("--allowedTools")
        allowed = command[tools_idx + 1]
        assert "Bash" not in allowed
        assert "WebFetch" not in allowed
        assert "Task" not in allowed
        for tool in ("Read", "Edit", "Write", "Glob", "Grep"):
            assert tool in allowed
        assert "--disallowedTools" not in command


class TestO_EditFilesChangedDetection:
    """Claude Code'un KENDİSİ ``files_changed`` raporlamaz -- JARVIS bunu
    SALT-OKUNUR ``git status --porcelain`` ile ayrıca tespit eder."""

    def test_success_reports_files_changed_from_readonly_git_status(self, monkeypatch, tmp_path):
        def _fake_run(command, **kwargs):
            if command and command[0] == "git":
                assert command[1:] == ["status", "--porcelain"]
                return _completed(
                    returncode=0,
                    stdout=" M src/example.py\n?? new_file.py\n",
                )
            return _completed(stdout=_success_json())

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        result = ClaudeCodeWorker().run_edit("test prompt", cwd=tmp_path)

        assert result.success is True
        assert "src/example.py" in result.files_changed
        assert "new_file.py" in result.files_changed

    def test_failure_never_calls_git_status_and_never_raises(self, monkeypatch, tmp_path):
        calls = []

        def _fake_run(command, **kwargs):
            calls.append(command)
            return _completed(returncode=1, stderr="boom")

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        result = ClaudeCodeWorker().run_edit("test prompt", cwd=tmp_path)  # çökmemeli

        assert result.success is False
        assert result.files_changed == ()
        assert len(calls) == 1  # yalnızca claude çağrısı; git status hiç YAPILMADI


class TestP_EditFailureIsTruthfulNotHanging:
    """Test H: başarısız Claude Code çalıştırması dürüst BLOCKED/FAILED
    durumu üretmeli, asla asılı/çökmüş bir durum bırakmamalı."""

    def test_timeout_maps_to_failed_result_not_exception(self, monkeypatch, tmp_path):
        import subprocess as subprocess_module

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )

        def _raise_timeout(*a, **kw):
            raise subprocess_module.TimeoutExpired(cmd="claude", timeout=60.0)

        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _raise_timeout)

        result = ClaudeCodeWorker().run_edit("test prompt", cwd=tmp_path)

        assert result.success is False
        assert result.exit_code is None
        from src.mission.failure_classification import FailureClass
        assert result.failure_class == FailureClass.TIMEOUT

    def test_missing_cli_maps_to_failed_result_not_exception(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.providers.claude_code_provider.shutil.which", lambda name: None)

        result = ClaudeCodeWorker().run_edit("test prompt", cwd=tmp_path)  # çökmemeli

        assert result.success is False
        assert result.exit_code is None


class TestQ_EditNoSecretsLeak:
    """Test F: yerleşik komut/ortamda API anahtarları/secret'lar
    SIZDIRILMAZ (aynı env-isolation deseni ``run_edit`` için de geçerli)."""

    def test_anthropic_secrets_are_stripped_from_edit_subprocess_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-key-should-not-leak")
        captured = {}

        def _fake_run(command, **kwargs):
            if command and command[0] == "git":
                return _completed(returncode=0, stdout="")
            captured["command"] = command
            captured["env"] = kwargs.get("env")
            return _completed(stdout=_success_json())

        monkeypatch.setattr(
            "src.providers.claude_code_provider.shutil.which",
            lambda name: r"C:\fake\claude.exe",
        )
        monkeypatch.setattr("src.providers.claude_code_provider.subprocess.run", _fake_run)

        ClaudeCodeWorker().run_edit("test prompt", cwd=tmp_path)

        assert "sk-fake-key-should-not-leak" not in " ".join(captured["command"])
        assert "ANTHROPIC_API_KEY" not in captured["env"]
