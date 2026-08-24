from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.control_center.store import ControlCenterStore
from src.workforce.accounts import AccountConnectionManager, GoogleYouTubeProvider, SCOPES
from src.workforce.manager import PROHIBITED_PERMISSIONS, WorkforceManager
from src.workforce.publisher import YouTubePublisher, artifact_id


class MemoryVault:
    def __init__(self): self.values = {}
    def store(self, ref, value): self.values[ref] = value
    def delete(self, ref): self.values.pop(ref, None)
    def resolve_for_publisher(self, ref): return self.values[ref]


class ProviderStub:
    def __init__(self): self.vault = MemoryVault(); self.verify_result = {"status": "CONNECTED", "verified": True,
        "remote_channel_id": "remote-de", "channel_title": "DE", "last_verified_at": "2026-08-17T00:00:00Z"}
    def begin(self, **kwargs): return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth", "secrets_exposed": False, **kwargs}
    def verify(self, ref): return dict(self.verify_result)
    def disconnect(self, ref): self.vault.delete(ref)
    def upload_video(self, *args, **kwargs): return {"id": "remote-video"}
    def verify_video(self, *args, **kwargs): return {"verified": True}


@pytest.fixture
def setup(tmp_path):
    store = ControlCenterStore(tmp_path / "state.json")
    workforce = WorkforceManager(store)
    provider = ProviderStub()
    accounts = AccountConnectionManager(store, provider)
    return store, workforce, accounts


def connect(accounts, worker="deniz", channel="youtube-de", remote="remote-de"):
    return accounts.complete({"worker_id": worker, "channel_id": channel, "remote_channel_id": remote,
        "channel_title": remote, "granted_scopes": SCOPES, "credential_ref": f"opaque/{channel}",
        "connected_at": "2026-08-17T00:00:00Z"}, market="Germany", language="de-DE")


def test_account_metadata_persists_but_secret_is_redacted(setup):
    store, _, accounts = setup; row = connect(accounts)
    assert row["connection_status"] == "CONNECTED" and "credential_ref" not in row
    assert AccountConnectionManager(ControlCenterStore(store.path), accounts.provider).redacted_accounts() == [row]


def test_synthetic_secret_never_serialized_to_account_api(setup):
    _, _, accounts = setup; sentinel = "SYNTHETIC_SECRET_DO_NOT_LEAK"
    accounts.provider.vault.values["opaque/youtube-de"] = sentinel.encode(); connect(accounts)
    assert sentinel not in json.dumps(accounts.redacted_accounts())


def test_cross_channel_account_scope_is_rejected(setup):
    _, _, accounts = setup; account = connect(accounts)
    with pytest.raises(RuntimeError, match="SCOPE MISMATCH"):
        accounts.assert_scope(worker_id="ceren", channel_id="youtube-us", account_id=account["account_id"],
                              artifact_channel_id="youtube-us")


def test_oauth_uses_pkce_and_returns_no_secret():
    vault = MemoryVault(); vault.store("JARVIS/YOUTUBE/OAUTH_CLIENT", json.dumps({"client_id": "synthetic-client"}).encode())
    result = GoogleYouTubeProvider(vault).begin(worker_id="deniz", channel_id="youtube-de",
                                               redirect_uri="http://127.0.0.1/callback")
    assert "code_challenge=" in result["authorization_url"] and result["secrets_exposed"] is False
    assert "client_secret" not in result


def test_reauth_state_persists_and_preserves_channel(setup):
    store, _, accounts = setup; row = connect(accounts)
    accounts.provider.verify_result = {"status": "ACCOUNT_REAUTH_REQUIRED", "verified": False,
                                       "remote_channel_id": "remote-de"}
    assert accounts.verify(row["account_id"])["connection_status"] == "ACCOUNT_REAUTH_REQUIRED"
    assert store.snapshot()["channels"]["youtube-de"]["identity"]["status"] == "ACCOUNT_REAUTH_REQUIRED"


def test_schedule_timezone_persistence_duplicate_and_malformed_rejection(setup):
    store, workforce, _ = setup
    schedule = {"enabled": True, "timezone": "Europe/Berlin",
        "jobs": [{"job_type": "PRODUCTION", "days": [1, 4], "time": "10:00"}]}
    workforce.change_schedule("deniz", schedule)
    assert WorkforceManager(ControlCenterStore(store.path)).worker("deniz")["schedule"]["timezone"] == "Europe/Berlin"
    with pytest.raises(ValueError, match="Duplicate"):
        workforce.change_schedule("deniz", {**schedule, "jobs": schedule["jobs"] * 2})
    with pytest.raises(ValueError, match="Malformed"):
        workforce.change_schedule("deniz", {**schedule, "jobs": [{"job_type": "PRODUCTION", "days": [8], "time": "99:00"}]})


def test_schedule_defaults_disabled_shorts_first_and_budgets_conservative(setup):
    _, workforce, _ = setup; worker = workforce.worker("deniz"); channel = worker["channel"]
    assert worker["schedule"]["enabled"] is False
    assert channel["startup_policy"]["mode"] == "SHORTS_FIRST"
    assert channel["limits"]["daily_production_budget"] == channel["limits"]["daily_publication_budget"] == 1


def test_backlog_limit_blocks_new_large_production(setup):
    store, workforce, _ = setup
    store.update(lambda s: s["channels"]["youtube-de"]["production_queue"].extend(
        [{"status": "READY_FOR_APPROVAL"}, {"status": "READY_FOR_APPROVAL"}]))
    with pytest.raises(RuntimeError, match="BACKLOG_LIMIT"): workforce.assert_youtube_capacity("deniz")
    assert workforce.worker("deniz")["status"] == "WAITING_FOR_HUMAN"


def approval_state(store, path, account_id=""):
    binding = {"artifact_id": artifact_id(path), "artifact_path": str(path), "production_id": "p-new",
        "channel_id": "youtube-de", "artifact_channel_id": "youtube-de", "account_id": account_id, "worker_id": "deniz"}
    row = {"id": "approval-1", "status": "PENDING", "binding": binding,
           "publication_metadata": {"title": "New", "privacy_status": "private"}}
    store.update(lambda s: s["approvals"].append(row)); return row


def test_exact_artifact_binding_and_approval_is_not_publication(setup, tmp_path):
    store, _, accounts = setup; path = tmp_path / "new.mp4"; path.write_bytes(b"new-video")
    approval_state(store, path); publisher = YouTubePublisher(store, accounts)
    result = publisher.publish("approval-1", execute=False)
    assert result["status"] == "READY_FOR_APPROVAL" and not result["publish_allowed"]
    assert store.snapshot()["publications"] == []


def test_changed_or_previous_artifact_cannot_use_old_approval(setup, tmp_path):
    store, _, accounts = setup; path = tmp_path / "new.mp4"; path.write_bytes(b"version-one")
    approval_state(store, path); path.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="CHANGED"): YouTubePublisher(store, accounts).preflight("approval-1")


def test_publish_requires_connected_matching_account_even_after_approval(setup, tmp_path):
    store, _, accounts = setup; path = tmp_path / "new.mp4"; path.write_bytes(b"video")
    approval_state(store, path); store.update(lambda s: s["approvals"][0].update(status="APPROVED"))
    assert YouTubePublisher(store, accounts).publish("approval-1", execute=False)["status"] == "ACCOUNT_NOT_CONNECTED"


def test_approved_publication_cannot_be_replayed(setup, tmp_path):
    store, _, accounts = setup
    path = tmp_path / "video.mp4"; path.write_bytes(b"video")
    account = connect(accounts)
    approval_state(store, path, account["account_id"])
    store.update(lambda s: s["approvals"][0].update(status="APPROVED"))
    publisher = YouTubePublisher(store, accounts)
    publisher.publish("approval-1", execute=True)
    with pytest.raises(RuntimeError, match="APPROVAL_ALREADY_CONSUMED|HUMAN_APPROVAL_REQUIRED"):
        publisher.publish("approval-1", execute=True)


def test_remote_verification_is_only_terminal_publication_state(setup, tmp_path):
    store, _, accounts = setup; account = connect(accounts); path = tmp_path / "new.mp4"; path.write_bytes(b"video")
    approval_state(store, path, account["account_id"]); store.update(lambda s: s["approvals"][0].update(status="APPROVED"))
    result = YouTubePublisher(store, accounts).publish("approval-1", execute=True)
    assert result["publication_status"] == "PUBLISHED_VERIFIED" and result["remote_verified"] is True


def test_unverified_and_shorts_retention_rules(setup):
    store, workforce, _ = setup
    rows = [{"channel_id": "youtube-de", "production_id": f"p{i}", "remote_verified": verified,
             "verified_at": f"2026-08-{10+i:02d}T00:00:00Z", "content_type": "SHORT"}
            for i, verified in [(1, True), (2, True), (3, True), (4, False)]]
    store.update(lambda s: s["publications"].extend(rows)); plan = workforce.retention_plan("youtube-de")
    assert plan["verified_count"] == 3 and plan["shorts_counted"] is True
    assert plan["protected_production_ids"] == ["p2", "p3"] and [x["production_id"] for x in plan["eligible"]] == ["p1"]


def test_cleanup_failure_does_not_undo_verified_publication(setup):
    store, workforce, _ = setup
    store.update(lambda s: s["publications"].extend([{"channel_id": "youtube-de", "production_id": str(i),
        "remote_verified": True, "verified_at": str(i), "large_artifacts": ["outside.mp4"]} for i in range(3)]))
    with pytest.raises(ValueError): workforce.cleanup("youtube-de", execute=True)
    assert all(x["remote_verified"] for x in store.snapshot()["publications"])


def test_story_learning_and_channel_isolation_survive_restart(setup):
    store, _, _ = setup
    store.update(lambda s: s["channels"]["youtube-de"]["youtube_learning"]["story_state"].update(ending="cliffhanger"))
    restarted = WorkforceManager(ControlCenterStore(store.path))
    assert restarted.worker("deniz")["channel"]["youtube_learning"]["story_state"]["ending"] == "cliffhanger"
    assert "ending" not in restarted.worker("ceren")["channel"]["youtube_learning"]["story_state"]


def test_security_and_finance_boundaries_are_unrouteable(setup):
    _, workforce, _ = setup
    for worker in workforce.workers():
        assert {"youtube_publish", "real_money_trade", "account_delete", "two_factor_change"} <= set(worker["permissions"]["prohibited"])
    assert workforce.finance_review({"market_truth_source": True, "candidates": []})["real_money"] is False


def test_restart_preserves_account_schedule_and_decisions(setup):
    store, workforce, accounts = setup; connect(accounts)
    workforce.change_schedule("deniz", {"enabled": True, "timezone": "Europe/Berlin",
        "jobs": [{"job_type": "RESEARCH", "days": [0], "time": "09:00"}]})
    workforce.decision("deniz", goal="g", decision="CONTINUE SERIES", why="ending state", evidence={},
        capabilities_used=[], risk="LOW", expected_result="next episode")
    restarted = WorkforceManager(ControlCenterStore(store.path))
    assert restarted.worker("deniz")["schedule"]["enabled"] is True
    assert len(restarted.worker("deniz")["decision_history"]) == 1
    assert AccountConnectionManager(ControlCenterStore(store.path), accounts.provider).redacted_accounts()[0]["connection_status"] == "CONNECTED"
