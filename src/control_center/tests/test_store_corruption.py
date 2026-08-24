import json
import threading

import pytest

from src.control_center import store as store_module
from src.control_center.store import ControlCenterStore


@pytest.mark.parametrize("content", ["{", "not-json", ""])
def test_corrupt_state_is_quarantined_and_recovered_fail_closed(tmp_path, content):
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")
    state = ControlCenterStore(path).snapshot()
    integrity = state["state_integrity"]
    assert integrity["status"] == "CORRUPTED_RECOVERY_REQUIRED"
    assert integrity["approval_state_trusted"] is False
    assert state["approvals"] == []
    assert state["engines"]["finance"]["live_activation"] is False
    assert list(tmp_path.glob("state.json.corrupt-*"))


def test_valid_state_survives_restart(tmp_path):
    path = tmp_path / "state.json"
    store = ControlCenterStore(path)
    store.append("missions", {"id": "kept", "status": "COMPLETED"})
    assert ControlCenterStore(path).snapshot()["missions"][0]["id"] == "kept"


def test_corruption_recovery_flag_survives_restart_without_silent_reset(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"approvals": [', encoding="utf-8")
    first = ControlCenterStore(path).snapshot()
    second = ControlCenterStore(path).snapshot()
    assert second["state_integrity"] == first["state_integrity"]
    assert second["state_integrity"]["approval_state_trusted"] is False
    assert len(list(tmp_path.glob("state.json.corrupt-*"))) == 1


def test_concurrent_updates_remain_valid_json(tmp_path):
    store = ControlCenterStore(tmp_path / "state.json")
    threads = [threading.Thread(target=store.append, args=("notifications", {"id": i}, 100)) for i in range(25)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert len(json.loads(store.path.read_text(encoding="utf-8"))["notifications"]) == 25


# Sprint: research/production pipeline audit -- state concurrency fix. A
# real workforce run failed with:
#   [WinError 5] Access is denied: 'workspace\\control_center\\state.tmp'
#   -> 'workspace\\control_center\\state.json'
# test_concurrent_updates_remain_valid_json (above) does NOT reproduce this:
# it hammers ONE SHARED ControlCenterStore instance, which was already safe
# (a per-instance threading.RLock correctly serializes calls on the SAME
# object). The real bug pattern is DIFFERENT: department/workforce/media
# code paths each construct a FRESH ControlCenterStore() pointed at the SAME
# state.json (e.g. MediaManager.set_channel_scope, YouTubeLearningAgent.
# __init__) -- each with its OWN separate lock object before this fix, so
# concurrent writers could genuinely race on the ONE shared 'state.tmp'
# filename. This test reproduces THAT exact pattern.
def test_concurrent_writers_with_separate_store_instances_never_collide(tmp_path):
    path = tmp_path / "state.json"
    ControlCenterStore(path)  # create the file first, like a real running Control Center
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            # A FRESH instance per writer/thread -- exactly the real
            # pattern (MediaManager.set_channel_scope, YouTubeLearningAgent)
            # that produced the real [WinError 5].
            store = ControlCenterStore(path)
            store.update(lambda state: state.setdefault("missions", []).append({"id": f"m{i}"}))
        except BaseException as error:  # noqa: BLE001 -- must capture EVERYTHING, including WinError
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(60)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()

    assert not errors, f"concurrent writers raised: {errors}"
    final = json.loads(path.read_text(encoding="utf-8"))
    # No silent lost updates -- every one of the 60 concurrent writes landed.
    assert len(final["missions"]) == 60
    assert {m["id"] for m in final["missions"]} == {f"m{i}" for i in range(60)}
    # No leftover unique-named temp files from a successful run (crash-safety
    # cleanup only applies on failure, but a successful os.replace() should
    # never leave one behind).
    assert not list(tmp_path.glob("state.*.tmp"))


def test_write_uses_a_unique_temp_filename_each_time(tmp_path, monkeypatch):
    # Direct unit-level proof of the naming scheme itself: two sequential
    # writes must never reuse the same temp path (the OLD code always used
    # the one fixed 'state.tmp' for every write, which is what let
    # concurrent writers collide on Windows).
    from pathlib import Path
    path = tmp_path / "state.json"
    store = ControlCenterStore(path)
    seen_temp_paths: list[Path] = []
    original_write_text = Path.write_text

    def spy_write_text(self, *args, **kwargs):
        if self.name.startswith("state.") and self.suffix == ".tmp":
            seen_temp_paths.append(Path(self))
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy_write_text)
    store.update(lambda state: state.setdefault("missions", []).append({"id": "a"}))
    store.update(lambda state: state.setdefault("missions", []).append({"id": "b"}))

    assert len(seen_temp_paths) == 2
    assert seen_temp_paths[0] != seen_temp_paths[1]
    assert not list(tmp_path.glob("state.*.tmp"))  # both writes cleaned up after themselves


def test_transient_permission_error_on_replace_is_retried_and_recovers(tmp_path, monkeypatch):
    # A real verification run hit an intermittent [WinError 5] on
    # os.replace() even with a uniquely-named temp file -- did not
    # reproduce on retry/isolation, consistent with something else (e.g.
    # AV/indexer) transiently holding a handle on the freshly-written temp
    # file, not a logic race. A short bounded retry must absorb this.
    store = ControlCenterStore(tmp_path / "state.json")
    original_replace = store_module.os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError(5, "Access is denied")
        return original_replace(src, dst)

    monkeypatch.setattr(store_module.os, "replace", flaky_replace)
    monkeypatch.setattr(store_module.time, "sleep", lambda seconds: None)  # keep the test fast

    store.update(lambda state: state.setdefault("missions", []).append({"id": "recovered"}))

    assert calls["count"] == 3
    assert store.snapshot()["missions"][0]["id"] == "recovered"


def test_persistent_permission_error_on_replace_still_raises_not_silently_lost(tmp_path, monkeypatch):
    # The retry is BOUNDED -- a genuinely persistent failure must still
    # raise, never be silently swallowed (no silent lost update).
    store = ControlCenterStore(tmp_path / "state.json")

    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(store_module.os, "replace", always_denied)
    monkeypatch.setattr(store_module.time, "sleep", lambda seconds: None)

    with pytest.raises(PermissionError):
        store.update(lambda state: state.setdefault("missions", []).append({"id": "lost"}))
