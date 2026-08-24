from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.config.settings import PROJECT_ROOT
from src.providers.base_provider import BaseProvider

if TYPE_CHECKING:
    from src.mission.failure_classification import FailureClass


CODEX_EXECUTABLE_NAMES = ("codex.cmd", "codex")
DEFAULT_TIMEOUT_SECONDS = 60.0
RESOURCE_TYPE = "CODEX_CHATGPT_PLAN"
_LIMIT_SIGNALS = (
    "usage limit", "rate limit", "quota", "too many requests", "429",
    "you've hit your limit", "you have hit your limit",
)
_ACCOUNT_SIGNALS = (
    "not logged in", "login required", "account unavailable", "session unavailable",
)


@dataclass
class CodexResult:
    success: bool
    output: str
    stderr: str
    exit_code: Optional[int]
    duration_seconds: float
    failure_class: FailureClass
    resource_type: str = RESOURCE_TYPE


class CodexWorker:
    """Codex CLI'yi non-interactive ve salt-okunur coding worker olarak çalıştırır."""

    def __init__(
        self,
        *,
        executable: Optional[str] = None,
        cwd: Optional[Path] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._executable_override = executable
        self.cwd = cwd or PROJECT_ROOT
        self.timeout_seconds = timeout_seconds

    def _resolve_executable(self) -> Optional[str]:
        if self._executable_override:
            return self._executable_override
        for name in CODEX_EXECUTABLE_NAMES:
            resolved = shutil.which(name)
            if resolved:
                return resolved
        return None

    def is_available(self) -> bool:
        return self._resolve_executable() is not None

    def run(self, prompt: str) -> CodexResult:
        from src.mission.failure_classification import classify_failure

        executable = self._resolve_executable()
        if executable is None:
            text = "Codex CLI bulunamadı (PATH'te codex.cmd/codex yok)."
            return CodexResult(
                success=False, output=text, stderr="", exit_code=None,
                duration_seconds=0.0, failure_class=classify_failure(text),
            )

        # ``codex exec`` bu kurulu sürümün resmi non-interactive yoludur.
        # Salt-okunur sandbox korunur; approval/sandbox bypass seçenekleri yoktur.
        command = [
            executable, "exec", "--sandbox", "read-only", "--color", "never",
            "--ephemeral", prompt,
        ]
        started = time.monotonic()
        try:
            proc = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8",
                timeout=self.timeout_seconds, cwd=str(self.cwd), shell=False,
            )
        except subprocess.TimeoutExpired:
            text = f"Codex zaman aşımına uğradı ({self.timeout_seconds:.0f} sn)."
            return CodexResult(
                success=False, output=text, stderr="", exit_code=None,
                duration_seconds=round(time.monotonic() - started, 2),
                failure_class=classify_failure(text),
            )
        except FileNotFoundError:
            text = f'Codex CLI bulunamadı ("{executable}" çalıştırılamadı).'
            return CodexResult(
                success=False, output=text, stderr="", exit_code=None,
                duration_seconds=round(time.monotonic() - started, 2),
                failure_class=classify_failure(text),
            )

        return self._parse_result(proc, round(time.monotonic() - started, 2))

    @staticmethod
    def _parse_result(proc: "subprocess.CompletedProcess[str]", duration: float) -> CodexResult:
        from src.mission.failure_classification import FailureClass, classify_failure

        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        combined = f"{stdout}\n{stderr}".casefold()
        # Başarılı ``codex exec`` çağrısında stderr ilerleme/tool günlüğüdür
        # ve incelenen repository'den hata ifadeleri içerebilir. Bu yüzden
        # zero-exit false-success yalnız nihai stdout üzerinden aranır;
        # process başarısızsa gerçek hata iki akışta da olabilir.
        failure_signal_text = combined if proc.returncode != 0 else stdout.casefold()

        if any(signal in failure_signal_text for signal in _LIMIT_SIGNALS):
            text = f"codex sağlayıcı hatası: kullanım kotası aşıldı (limit aşıldı): {(stdout or stderr)[:400]}"
            return CodexResult(False, text, stderr, proc.returncode, duration, classify_failure(text))

        if any(signal in failure_signal_text for signal in _ACCOUNT_SIGNALS):
            text = f"codex sağlayıcı hatası: oturum/hesap kullanılamıyor: {(stdout or stderr)[:400]}"
            return CodexResult(False, text, stderr, proc.returncode, duration, classify_failure(text))

        if proc.returncode != 0:
            detail = (stderr or stdout or "bilinmeyen process hatası")[:400]
            text = f"codex sağlayıcı hatası (kod {proc.returncode}): {detail}"
            return CodexResult(False, text, stderr, proc.returncode, duration, classify_failure(text))

        if not stdout:
            text = "codex sağlayıcı hatası: boş cevap verdi."
            return CodexResult(False, text, stderr, proc.returncode, duration, classify_failure(text))

        return CodexResult(True, stdout, stderr, proc.returncode, duration, FailureClass.UNKNOWN)


class CodexProvider(BaseProvider):
    """Codex ChatGPT-plan CLI kaynağını mevcut provider sözleşmesine bağlar."""

    resource_type = RESOURCE_TYPE

    def __init__(self, worker: Optional[CodexWorker] = None) -> None:
        super().__init__("codex")
        self.worker = worker or CodexWorker()
        self.last_result: Optional[CodexResult] = None

    def is_available(self) -> bool:
        return self.worker.is_available()

    def generate(self, prompt: str, model: str | None = None) -> str:
        result = self.worker.run(prompt)
        self.last_result = result
        return result.output
