from pathlib import Path
import json

from src.integration.moneyprinterturbo import (
    PINNED_REVISION,
    MoneyPrinterTurboBridge,
)


def _ready_root(tmp_path: Path) -> Path:
    root = tmp_path / "MoneyPrinterTurbo"
    python = root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"fake-python")
    (root / "cli.py").write_text("# pinned upstream cli\n", encoding="utf-8")
    (root / "config.toml").write_text(
        'llm_provider = "claude_code"\n'
        'upload_post_enabled = false\n'
        'upload_post_auto_upload = false\n',
        encoding="utf-8",
    )
    return root


def test_bridge_requires_publishing_lock_and_isolated_python(tmp_path):
    root = _ready_root(tmp_path)
    status = MoneyPrinterTurboBridge(root).status()
    assert status.ready is True
    assert status.publishing_disabled is True
    assert status.revision == PINNED_REVISION
    assert status.python.endswith("python.exe")


def test_bridge_fails_closed_when_upstream_publishing_is_enabled(tmp_path):
    root = _ready_root(tmp_path)
    (root / "config.toml").write_text(
        'upload_post_enabled = true\nupload_post_auto_upload = false\n',
        encoding="utf-8",
    )
    status = MoneyPrinterTurboBridge(root).status()
    assert status.installed is True
    assert status.ready is False
    assert "kilidi" in status.detail


def test_bridge_reports_persistent_setup_failure_and_repairable_partial_source(tmp_path):
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    (root / "cli.py").write_text("# source exists but venv failed\n", encoding="utf-8")
    (tmp_path / "MoneyPrinterTurbo.setup.json").write_text(json.dumps({
        "status": "FAILED", "message": "dependency sync failed",
    }), encoding="utf-8")
    status = MoneyPrinterTurboBridge(root).status()
    assert status.installed is True and status.ready is False
    assert status.setup_state == "FAILED"
    assert status.setup_error == "dependency sync failed"
    assert "dependency sync failed" in status.detail


def test_windows_installer_preserves_unmanaged_copy_and_validates_runtime():
    script = (Path(__file__).resolve().parents[3] / "tools" / "setup_moneyprinterturbo.ps1").read_text(encoding="utf-8")
    assert "MoneyPrinterTurbo.setup.json" in script
    assert "Move-Item -LiteralPath $IntegrationRoot" in script
    assert "uvPath sync --frozen --no-dev --python $systemPython" in script
    assert "import moviepy, edge_tts" in script
    assert "Write-SetupState 'FAILED'" in script
    assert "Get-Command $Name -CommandType Application -All" in script
    assert "notmatch '\\\\WindowsApps\\\\'" in script
    assert "& $pyPath $selector" in script
    assert "& $pythonPath -c" in script


def test_command_uses_only_local_materials_and_no_publish_switch(tmp_path):
    root = _ready_root(tmp_path)
    material = tmp_path / "licensed.mp4"
    material.write_bytes(b"licensed-media")
    command = MoneyPrinterTurboBridge(root).build_command(
        subject="İsviçre gündemi",
        script="Özgün Türkçe anlatım.",
        material_paths=[material],
        task_id="f6d43098-7baa-4447-875c-9477ec371f0e",
    )
    assert command[command.index("--video-source") + 1] == "local"
    assert command[command.index("--video-aspect") + 1] == "9:16"
    assert command[command.index("--voice-name") + 1] == "tr-TR-EmelNeural"
    assert command[command.index("--bgm-type") + 1] == "none"
    assert not any("publish" in part.casefold() or "upload-post" in part.casefold() for part in command)


def test_safe_environment_removes_paid_media_and_publish_credentials(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "secret")
    monkeypatch.setenv("UPLOAD_POST_API_KEY", "secret")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "subscription-token")
    env = MoneyPrinterTurboBridge._safe_environment()
    assert "PEXELS_API_KEY" not in env
    assert "UPLOAD_POST_API_KEY" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "subscription-token"
    assert env["MPT_DISABLE_PUBLISHING"] == "1"

