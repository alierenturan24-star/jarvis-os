import subprocess

from src.utils import windows_process


def test_other_platforms_passthrough(monkeypatch):
    called = {}
    monkeypatch.setattr(windows_process, "_no_window_creationflags", lambda: 0)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: called.update(kwargs=kw) or "ok")
    assert windows_process.run_quietly(["git", "status"], timeout=1) == "ok"
    assert called["kwargs"] == {"timeout": 1}


def test_windows_hidden_creationflags(monkeypatch):
    called = {}
    monkeypatch.setattr(windows_process, "_no_window_creationflags", lambda: 0x08000000)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: called.update(kwargs=kw) or "ok")
    assert windows_process.run_quietly(["git"], creationflags=16) == "ok"
    assert called["kwargs"]["creationflags"] == 0x08000010
