class ToolSelector:

    def __init__(self):

        self.intent_map = {
            "browser": "browser",
            "file": "file",
            "folder": "folder",
            "program": "program",
        }

    def select(self, intent):

        return self.intent_map.get(intent)