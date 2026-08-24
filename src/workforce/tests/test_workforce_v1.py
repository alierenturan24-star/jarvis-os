import json
from pathlib import Path

import pytest

from src.control_center.store import ControlCenterStore
from src.media.channel_store import ChannelScopedStore
from src.media.production import PRODUCTION_CAPABILITIES
from src.workforce.manager import WorkforceManager
from src.workforce.vault import CredentialReference, WindowsCredentialVault


@pytest.fixture
def store(tmp_path):
    return ControlCenterStore(tmp_path / "state.json")


@pytest.fixture
def workforce(store):
    return WorkforceManager(store)


def test_seven_persistent_workers_reload_with_identity(workforce, store):
    assert [w["name"] for w in workforce.workers()] == ["DENİZ", "CEREN", "SİNEM", "EREN", "CEMO", "EYLEM", "ALİ"]
    restarted = WorkforceManager(ControlCenterStore(store.path))
    assert [(w["worker_id"], w["role"]) for w in restarted.workers()] == [(w["worker_id"], w["role"]) for w in workforce.workers()]


def test_market_language_scopes(workforce):
    assert workforce.worker("deniz")["channel"]["market"] == "Germany"
    assert workforce.worker("deniz")["channel"]["language"] == "de-DE"
    assert workforce.worker("ceren")["channel"]["market"] == "United States"
    assert workforce.worker("ceren")["channel"]["language"] == "en-US"
    assert workforce.worker("sinem")["channel"]["market"] == "Switzerland"
    assert workforce.worker("sinem")["channel"]["language"] == "CHANNEL_CONFIG"


def test_channel_memories_are_isolated(store, workforce):
    de = ChannelScopedStore(store, "youtube-de"); us = ChannelScopedStore(store, "youtube-us")
    de.update(lambda state: state["youtube_learning"]["titles"].append("Nur Deutschland"))
    assert de.snapshot()["youtube_learning"]["titles"] == ["Nur Deutschland"]
    assert us.snapshot()["youtube_learning"]["titles"] == []


def test_youtube_worker_routes_existing_production_capabilities(workforce):
    access = workforce.worker("deniz")["capability_access"]
    assert set(PRODUCTION_CAPABILITIES) - {"technical_validation", "semantic_validation"} <= set(access)
    assert "[WORKFORCE_CHANNEL:youtube-de]" in workforce.youtube_goal("deniz")


def test_shorts_first_is_adaptive_and_analytics_not_connected(workforce):
    channel = workforce.worker("ceren")["channel"]
    assert channel["startup_policy"] == {"mode": "SHORTS_FIRST", "adaptive_when_analytics_available": True}
    assert channel["youtube_learning"]["analytics"]["source"] == "NOT_CONNECTED"


def test_pause_resume_disable(workforce):
    assert workforce.pause("deniz")["status"] == "PAUSED"
    assert workforce.resume("deniz")["status"] == "IDLE"
    disabled = workforce.disable("deniz")
    assert disabled["enabled"] is False and disabled["status"] == "PAUSED"


def test_scheduler_persists_and_rejects_duplicate_execution(workforce, store):
    workforce.change_schedule("ali", {"enabled": True, "cron": "0 9 * * *", "next_run_at": "2026-08-17T09:00:00Z"})
    execution = workforce.claim_execution("ali", "2026-08-17T09:00:00Z")
    with pytest.raises(RuntimeError, match="Duplicate"):
        workforce.claim_execution("ali", "2026-08-17T09:00:00Z")
    restarted = WorkforceManager(ControlCenterStore(store.path))
    assert restarted.worker("ali")["schedule"]["last_execution_id"] == execution


def test_missed_schedule_becomes_recovery_required(workforce):
    workforce.change_schedule("deniz", {"enabled": True, "cron": "daily", "next_run_at": "2020-01-01T00:00:00Z"})
    assert workforce.evaluate_missed_schedules() == ["deniz"]
    assert workforce.worker("deniz")["status"] == "RECOVERY_REQUIRED"


def test_interrupted_work_becomes_recovery_required(store, workforce):
    workforce.set_status("deniz", "WORKING")
    ControlCenterStore(store.path).recover_interrupted()
    assert WorkforceManager(ControlCenterStore(store.path)).worker("deniz")["status"] == "RECOVERY_REQUIRED"


def test_decision_log_persists(workforce, store):
    row = workforce.decision("eren", goal="explore", decision="REVIEW", why="evidence complete",
        evidence={"lab": "x"}, capabilities_used=["backtest"], risk="PAPER_ONLY", expected_result="CEMO review")
    assert WorkforceManager(ControlCenterStore(store.path)).worker("eren")["decision_history"][0]["decision_id"] == row["decision_id"]


def test_eylem_is_independent_and_cannot_produce(workforce):
    eylem = workforce.worker("eylem")
    assert "video_render" not in eylem["capability_access"]
    assert {"technical_validation", "semantic_validation"} <= set(eylem["capability_access"])


def test_cemo_rejects_missing_evidence_and_real_money(workforce):
    review = workforce.finance_review({"market_truth_source": True, "fees_rate": .001, "slippage_rate": .0005, "candidates": []})
    assert review["decision"] == "REJECTED" and review["real_money"] is False


def test_eren_cannot_self_qualify_and_finance_permissions_forbid_live(workforce):
    eren = workforce.worker("eren")
    assert "paper_qualification" not in eren["capability_access"]
    assert "real_money_trade" in eren["permissions"]["prohibited"]


def test_vault_model_contains_reference_not_secret():
    ref = CredentialReference("a", "youtube", "youtube-de", "deniz", "wincred:youtube/a", ("upload",))
    serialized = json.dumps(ref.__dict__)
    assert "password" not in serialized and "token" not in serialized and ref.status == "NOT_CONNECTED"
    assert WindowsCredentialVault().backend == "WINDOWS_CREDENTIAL_MANAGER"


def test_account_security_and_publish_require_human(workforce):
    worker = workforce.worker("deniz")
    assert {"password_change", "two_factor_change", "account_delete", "youtube_publish"} <= set(worker["permissions"]["prohibited"])


def _publication(pid, verified, path="", kind="SHORT"):
    return {"production_id": pid, "channel_id": "youtube-de", "remote_verified": verified,
            "verified_at": f"2026-08-{pid[-2:]}T10:00:00Z", "content_type": kind,
            "large_artifacts": [path] if path else []}


def test_two_verified_publications_retention_counts_shorts(store, workforce):
    store.update(lambda s: s["publications"].extend([
        _publication("p01", True, kind="SHORT"), _publication("p02", True, kind="LONG"),
        _publication("p03", True, kind="SHORT"), _publication("p04", False)]))
    plan = workforce.retention_plan("youtube-de")
    assert plan["shorts_counted"] is True and plan["protected_production_ids"] == ["p02", "p03"]
    assert [p["production_id"] for p in plan["eligible"]] == ["p01"]


def test_unverified_publication_is_never_cleanup_eligible(store, workforce):
    store.update(lambda s: s["publications"].extend([_publication("p01", True), _publication("p02", True),
                                                     _publication("p03", True), _publication("p99", False)]))
    assert "p99" not in [p["production_id"] for p in workforce.retention_plan("youtube-de")["eligible"]]


def test_safe_cleanup_deletes_only_old_verified_large_artifact(tmp_path, store, workforce, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workspace = tmp_path / "workspace"; workspace.mkdir()
    old = workspace / "old.mp4"; old.write_bytes(b"large")
    store.update(lambda s: s["publications"].extend([_publication("p01", True, str(old)),
        _publication("p02", True), _publication("p03", True)]))
    result = workforce.cleanup("youtube-de", execute=True)
    assert not old.exists() and str(old.resolve()) in result["deleted"]
    assert store.snapshot()["channels"]["youtube-de"]["youtube_learning"] is not None


def test_cleanup_rejects_outside_workspace(tmp_path, store, workforce, monkeypatch):
    monkeypatch.chdir(tmp_path); (tmp_path / "workspace").mkdir()
    outside = tmp_path / "outside.mp4"; outside.write_bytes(b"x")
    store.update(lambda s: s["publications"].extend([_publication("p01", True, str(outside)),
        _publication("p02", True), _publication("p03", True)]))
    with pytest.raises(ValueError, match="rejected"):
        workforce.cleanup("youtube-de", execute=True)
    assert outside.exists()


def test_state_and_worker_ui_contract_never_contains_secret_values(workforce, store):
    state = store.snapshot()
    def keys(value):
        if isinstance(value, dict):
            return {str(k).casefold() for k in value} | set().union(*(keys(v) for v in value.values()))
        if isinstance(value, list): return set().union(*(keys(v) for v in value), set())
        return set()
    assert not ({"refresh_token", "api_secret", "password", "credential_value"} & keys(state))
    assert workforce.worker("deniz")["channel"]["identity"]["status"] == "NOT_CONNECTED"
