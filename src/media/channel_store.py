from __future__ import annotations

from copy import deepcopy


def _empty_youtube_learning() -> dict:
    """Return the minimum durable shape expected by the media pipeline.

    Real installations can carry state written by much older JARVIS builds.
    Some of those builds persisted ``null`` for a collection after an
    interrupted write. Treating that historical value as today's schema
    used to crash media startup before a single frame was produced.
    """
    return {
        "productions": [], "characters": {}, "experiments": [],
        "learned_patterns": [], "next_production_changes": [],
        "analytics": {"source": "NOT_CONNECTED", "records": []},
    }


def normalize_youtube_learning(value) -> dict:
    base = _empty_youtube_learning()
    if isinstance(value, dict):
        base.update(value)
    for key in ("productions", "experiments", "learned_patterns", "next_production_changes"):
        if not isinstance(base.get(key), list):
            base[key] = []
    if not isinstance(base.get("characters"), dict):
        base["characters"] = {}
    if not isinstance(base.get("analytics"), dict):
        base["analytics"] = {"source": "NOT_CONNECTED", "records": []}
    base["analytics"].setdefault("source", "NOT_CONNECTED")
    if not isinstance(base["analytics"].get("records"), list):
        base["analytics"]["records"] = []
    return base


class ChannelScopedStore:
    """Expose one channel's private memory through the legacy store contract."""
    def __init__(self, store, channel_id: str) -> None:
        self.store, self.channel_id = store, channel_id

    def snapshot(self):
        state = self.store.snapshot()
        scoped = deepcopy(state)
        channel = (state.get("channels") or {}).get(self.channel_id)
        if not isinstance(channel, dict):
            raise KeyError(f"YouTube channel state missing for {self.channel_id!r}")
        scoped["youtube_learning"] = normalize_youtube_learning(channel.get("youtube_learning"))
        return scoped

    def update(self, mutator):
        def scoped_mutate(state):
            view = deepcopy(state)
            channel = (state.get("channels") or {}).get(self.channel_id)
            if not isinstance(channel, dict):
                raise KeyError(f"YouTube channel state missing for {self.channel_id!r}")
            view["youtube_learning"] = normalize_youtube_learning(channel.get("youtube_learning"))
            mutator(view)
            channel["youtube_learning"] = normalize_youtube_learning(view.get("youtube_learning"))
        return self.store.update(scoped_mutate)
