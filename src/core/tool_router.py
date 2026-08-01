class ToolRouter:

    def __init__(self):

        self.routes = {
            "browser": "browser",
            "file": "file",
            "folder": "folder",
            "program": "program",
            "search": "web_search",
        }

    def get_tool(self, intent):

        return self.routes.get(intent)