from __future__ import annotations

import os
import json
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


UPSTREAM_REPOSITORY = "https://github.com/harry0703/MoneyPrinterTurbo"
PINNED_VERSION = "1.3.8"
PINNED_REVISION = "c184fccd05621d7a654b6e6ea34102a0a0de0657"
DEFAULT_TIMEOUT_SECONDS = 20 * 60


@dataclass(frozen=True)
class MoneyPrinterTurboStatus:
    installed: bool
    ready: bool
    root: str
    python: str
    version: str = PINNED_VERSION
    revision: str = PINNED_REVISION
    claude_cli: bool = False
    publishing_disabled: bool = True
    detail: str = ""
    setup_state: str = "NOT_STARTED"
    setup_error: str = ""


@dataclass(frozen=True)
class MoneyPrinterTurboRenderResult:
    success: bool
    artifact_path: str = ""
    task_id: str = ""
    error: str = ""


def _candidate_roots() -> tuple[Path, ...]:
    configured = os.getenv("MONEYPRINTERTURBO_ROOT", "").strip()
    project_root = Path(__file__).resolve().parents[2]
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    # The managed installer deliberately lives outside JARVIS' rotating
    # release worktrees.  A new JARVIS build can therefore reuse the same
    # isolated MPT environment instead of downloading it again.
    candidates.append(project_root.parent / "jarvis-integrations" / "MoneyPrinterTurbo")
    candidates.append(Path("C:/Projects/jarvis-integrations/MoneyPrinterTurbo"))
    candidates.append(Path("C:/Projects/MoneyPrinterTurbo"))
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return tuple(unique)


def _python_for(root: Path) -> Path | None:
    candidates = (
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
        root / "runtime" / "python.exe",
        root / "python" / "python.exe",
    )
    return next((path for path in candidates if path.is_file()), None)


def _publishing_is_disabled(root: Path) -> bool:
    config_path = root / "config.toml"
    if not config_path.is_file():
        return False
    try:
        text = config_path.read_text(encoding="utf-8").casefold()
    except OSError:
        return False
    return (
        "upload_post_enabled = false" in text
        and "upload_post_auto_upload = false" in text
    )


def _setup_state(root: Path) -> dict:
    path = root.parent / "MoneyPrinterTurbo.setup.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"status": "UNKNOWN", "message": "Kurulum durum kaydı okunamadı."}


class MoneyPrinterTurboBridge:
    """Safe, local-only bridge to the upstream MoneyPrinterTurbo CLI.

    JARVIS supplies already-approved local media paths and an original script.
    The bridge never selects an online/paid media source and never calls the
    upstream publishing integration.  MoneyPrinterTurbo stays in its own venv,
    avoiding dependency conflicts with the control center.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root).expanduser() if root else self._discover_root()

    @staticmethod
    def _discover_root() -> Path:
        return next(
            (candidate for candidate in _candidate_roots() if (candidate / "cli.py").is_file()),
            _candidate_roots()[0],
        )

    def status(self) -> MoneyPrinterTurboStatus:
        root = self.root.resolve()
        cli = root / "cli.py"
        python = _python_for(root)
        installed = cli.is_file()
        publishing_disabled = _publishing_is_disabled(root)
        setup = _setup_state(root)
        setup_state = str(setup.get("status") or "NOT_STARTED").upper()
        setup_error = str(setup.get("message") or "")[:1000] if setup_state == "FAILED" else ""
        ready = bool(installed and python and publishing_disabled)
        if ready:
            detail = "Yerel kurgu motoru hazır; Claude Code bağlantısı kullanılabilir, yayın kapalı."
        elif setup_state == "RUNNING":
            detail = "Ayrı Python ortamı ve bağımlılıklar kuruluyor; JARVIS açık kalabilir."
        elif setup_state == "FAILED":
            detail = f"Kurulum tamamlanamadı: {setup_error or 'ayrıntı kaydı yok'}"
        elif installed and not python:
            detail = "Kaynak hazır; ayrı Python ortamı eksik. Güvenli kurulum kaldığı yerden devam edebilir."
        elif installed and not publishing_disabled:
            detail = "Yayın güvenlik kilidi doğrulanamadı; motor kullanılmayacak."
        else:
            detail = "Henüz kurulmadı; panelden arka planda güvenli kurulum başlatılabilir."
        return MoneyPrinterTurboStatus(
            installed=installed,
            ready=ready,
            root=str(root),
            python=str(python.resolve()) if python else "",
            claude_cli=bool(shutil.which("claude") or shutil.which("claude.exe")),
            publishing_disabled=publishing_disabled,
            detail=detail,
            setup_state="READY" if ready else setup_state,
            setup_error=setup_error,
        )

    def status_dict(self) -> dict:
        return asdict(self.status())

    def build_command(
        self, *, subject: str, script: str, material_paths: list[str | Path],
        task_id: str,
    ) -> list[str]:
        status = self.status()
        if not status.ready:
            raise RuntimeError(status.detail)
        materials = [str(Path(path).resolve()) for path in material_paths]
        if not materials or not all(Path(path).is_file() for path in materials):
            raise ValueError("MoneyPrinterTurbo için doğrulanmış yerel medya dosyaları gerekli.")
        return [
            status.python, str((self.root / "cli.py").resolve()),
            "--video-subject", subject.strip(),
            "--video-script", script.strip(),
            "--video-source", "local",
            "--video-materials", ",".join(materials),
            "--video-aspect", "9:16",
            "--video-fit-mode", "cover",
            "--video-concat-mode", "sequential",
            "--video-transition-mode", "fade-in",
            "--video-clip-duration", "5",
            "--voice-name", "tr-TR-EmelNeural",
            "--video-language", "tr-TR",
            "--subtitle-enabled",
            "--bgm-type", "none",
            "--n-threads", "2",
            "--video-count", "1",
            "--task-id", task_id,
            "--stop-at", "video",
        ]

    def render(
        self, *, subject: str, script: str, material_paths: list[str | Path],
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> MoneyPrinterTurboRenderResult:
        task_id = str(uuid.uuid4())
        try:
            command = self.build_command(
                subject=subject, script=script, material_paths=material_paths, task_id=task_id,
            )
            completed = subprocess.run(
                command, cwd=self.root, capture_output=True, text=True,
                timeout=max(60, min(int(timeout_seconds), DEFAULT_TIMEOUT_SECONDS)),
                check=False,
                env=self._safe_environment(),
            )
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            return MoneyPrinterTurboRenderResult(False, task_id=task_id, error=str(error))
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "bilinmeyen hata").strip()[-2000:]
            return MoneyPrinterTurboRenderResult(
                False, task_id=task_id, error=f"MoneyPrinterTurbo çıkış kodu {completed.returncode}: {detail}",
            )
        task_root = self.root / "storage" / "tasks" / task_id
        outputs = sorted(path for path in task_root.glob("final-*.mp4") if path.stat().st_size > 0)
        if not outputs:
            return MoneyPrinterTurboRenderResult(
                False, task_id=task_id, error="MoneyPrinterTurbo geçerli MP4 üretmedi.",
            )
        return MoneyPrinterTurboRenderResult(
            True, artifact_path=str(outputs[0].resolve()), task_id=task_id,
        )

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        env = dict(os.environ)
        # Never let a stray paid API configuration turn a local edit into an
        # external generation or publication call.  Claude Code subscription
        # auth is intentionally preserved; it is not needed for the supplied
        # script/local-material render path but remains available in MPT's UI.
        for name in tuple(env):
            upper = name.upper()
            if upper.startswith("UPLOAD_POST_") or upper in {
                "PEXELS_API_KEY", "PIXABAY_API_KEY", "COVERR_API_KEY",
                "SONILO_API_KEY", "ELEVENLABS_API_KEY",
            }:
                env.pop(name, None)
        env["MPT_DISABLE_PUBLISHING"] = "1"
        return env

