from src.capabilities.capability import Capability


class CapabilityRegistry:

    def __init__(self):

        self.capabilities = {}

    def register(self, capability: Capability):

        self.capabilities[capability.id] = capability

    def get(self, capability_id):

        return self.capabilities.get(capability_id)

    def all(self):

        return list(self.capabilities.values())

    def enabled(self):

        return [
            c
            for c in self.capabilities.values()
            if c.enabled
        ]

    def disable(self, capability_id):

        if capability_id in self.capabilities:

            self.capabilities[capability_id].enabled = False

    def enable(self, capability_id):

        if capability_id in self.capabilities:

            self.capabilities[capability_id].enabled = True