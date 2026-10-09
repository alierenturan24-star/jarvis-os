import json

from src.control_center.store import ControlCenterStore
from src.media.channel_store import ChannelScopedStore
from src.media.learning import YouTubeLearningAgent
from src.media.quality import _probe_dimensions


def test_legacy_null_learning_collections_are_normalized(tmp_path):
    store = ControlCenterStore(tmp_path / "state.json")
    store.update(lambda state: state["channels"].update({
        "youtube-ch": {
            "channel_id": "youtube-ch", "market": "Switzerland", "language": "tr-TR",
            "youtube_learning": {
                "productions": None, "characters": None, "experiments": None,
                "next_production_changes": None, "analytics": None,
            },
        },
    }))
    scoped = ChannelScopedStore(store, "youtube-ch")
    memory = scoped.snapshot()["youtube_learning"]
    assert memory["productions"] == []
    assert memory["characters"] == {}
    assert memory["analytics"]["source"] == "NOT_CONNECTED"
    assert YouTubeLearningAgent(scoped).production_plan("güncel haber")["based_on_productions"] == []


def test_character_refresh_repairs_old_partial_production_records(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"real-reference")
    asset = tmp_path / "workspace" / "assets" / "media" / "legacy"
    asset.mkdir(parents=True)
    (asset / "production.json").write_text(json.dumps({
        "character_identity": {"name": "Leni", "reference_asset_paths": [str(reference)]},
        "successful_poses": [], "failed_poses": [],
    }), encoding="utf-8")
    store = ControlCenterStore()
    store.update(lambda state: state["youtube_learning"].update(
        productions=[{"creative": None, "quality": None}],
    ))
    imported = YouTubeLearningAgent(store).refresh_character_memory()
    record = store.snapshot()["youtube_learning"]["productions"][0]
    assert imported == 1
    assert record["creative"]["main_character_identity"] == "Leni"
    assert record["quality"]["character_consistency"] == 94


def test_null_ffprobe_streams_fails_closed_instead_of_crashing(monkeypatch, tmp_path):
    class Result:
        stdout = '{"streams": null}'
    monkeypatch.setattr("src.media.quality.subprocess.run", lambda *args, **kwargs: Result())
    assert _probe_dimensions(tmp_path / "video.mp4", "ffprobe") is None
