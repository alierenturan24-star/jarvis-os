from pathlib import Path
from types import SimpleNamespace

from src.control_center.store import ControlCenterStore
from src.media.learning import YouTubeLearningAgent


def test_learning_persists_restart_and_influences_next_plan(tmp_path, monkeypatch):
    store_path = tmp_path / "state.json"
    artifact = tmp_path / "video.mp4"
    artifact.write_bytes(b"0" * 2048)
    artifact.with_suffix(".quality.json").write_text("""{
      "goal":"German kids cartoon", "production_backend":"authored_animation",
      "placeholder":false, "fallback":false, "duration_seconds":60,
      "story_beats":["HOOK","SETUP","PROBLEM","ACTION","RESOLUTION","ENDING"],
      "scene_files":["a","b","c","d","e","f"], "script":"eins zwei drei",
      "character_consistency_score":92, "character_identity":{"name":"Leni","canonical_appearance":{"hair":"brown"}},
      "successful_poses":["run-left"], "narration_language":"de-DE"
    }""", encoding="utf-8")
    result = SimpleNamespace(passed=True, technical_passed=True, semantic_passed=True, issues=(),
        scene_count=6, detected_cuts=5, max_audio_db=-4.0, body_motion_detected=True, body_motion_ratio=2.5)
    monkeypatch.setattr("src.media.learning.validate_media_goal_artifact", lambda *_: result)
    first = YouTubeLearningAgent(ControlCenterStore(store_path))
    record = first.record(goal="German kids cartoon", artifact_path=str(artifact), plan_text="plan one")
    restarted = YouTubeLearningAgent(ControlCenterStore(store_path))
    plan = restarted.production_plan("second story")
    assert plan["based_on_productions"] == [record["production_id"]]
    assert plan["avoid_exact_reuse"][0]["script"] == record["fingerprints"]["script"]
    assert restarted.store.snapshot()["youtube_learning"]["characters"]["Leni"]["successful_poses"] == ["run-left"]
    assert restarted.store.snapshot()["youtube_learning"]["analytics"]["source"] == "NOT_CONNECTED"
    assert all(value is None for key, value in record["performance"].items() if key != "source")


def test_failure_learning_is_specific_not_provider_blacklist(tmp_path, monkeypatch):
    artifact = tmp_path / "bad.mp4"; artifact.write_bytes(b"0" * 2048)
    artifact.with_suffix(".quality.json").write_text(
        '{"placeholder":false,"scene_files":["a","b","c","d"],"story_beats":["HOOK"]}', encoding="utf-8")
    result = SimpleNamespace(passed=False, technical_passed=True, semantic_passed=False,
        issues=("declared character motion is camera/global motion only",), scene_count=4,
        detected_cuts=3, max_audio_db=-4.0, body_motion_detected=False, body_motion_ratio=.7)
    monkeypatch.setattr("src.media.learning.validate_media_goal_artifact", lambda *_: result)
    agent = YouTubeLearningAgent(ControlCenterStore(tmp_path / "state.json"))
    record = agent.record(goal="running character", artifact_path=str(artifact), plan_text="script")
    changes = " ".join(record["learning"]["change_next"])
    assert "pose diversity" in changes and "FFmpeg" not in changes
    assert record["quality"]["production_readiness"] is False
