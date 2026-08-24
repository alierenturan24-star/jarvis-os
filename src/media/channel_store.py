from __future__ import annotations

from copy import deepcopy


class ChannelScopedStore:
    """Expose one channel's private memory through the legacy store contract."""
    def __init__(self, store, channel_id: str) -> None:
        self.store, self.channel_id = store, channel_id

    def snapshot(self):
        state = self.store.snapshot()
        scoped = deepcopy(state)
        scoped["youtube_learning"] = deepcopy(state["channels"][self.channel_id]["youtube_learning"])
        return scoped

    def update(self, mutator):
        def scoped_mutate(state):
            view = deepcopy(state)
            view["youtube_learning"] = deepcopy(state["channels"][self.channel_id]["youtube_learning"])
            mutator(view)
            state["channels"][self.channel_id]["youtube_learning"] = view["youtube_learning"]
        return self.store.update(scoped_mutate)
