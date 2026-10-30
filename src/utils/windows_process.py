"""Prevent black CMD/PowerShell windows from flashing during CLI subprocesses."""

from __future__ import annotations

import os
import subprocess
from typing import Any


def _no_window_creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def run_quietly(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    """Preserve run() semantics and hide spawned Windows console windows."""
    flags = _no_window_creationflags()
    if flags:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | flags
    return subprocess.run(*args, **kwargs)
