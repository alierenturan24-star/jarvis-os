from src.tools.file_tool import FileTool
from src.tools.folder_tool import FolderTool
from src.tools.web_search_tool import WebSearchTool


class ToolManager:

    def __init__(self):
        self.tools = {
            "file": FileTool(),
            "folder": FolderTool(),
            "web_search": WebSearchTool(),
        }

    def has_tool(self, name):
        return name in self.tools

    def get_tool(self, name):
        return self.tools.get(name)

    def execute(self, tool_name, **kwargs):
        tool = self.get_tool(tool_name)

        if tool is None:
            return f"{tool_name} bulunamadı."

        return tool.execute(**kwargs)

    def list_tools(self):
        return [
            tool.get_info()
            for tool in self.tools.values()
        ]