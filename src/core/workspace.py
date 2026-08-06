from pathlib import Path
from datetime import datetime


class Workspace:

    def __init__(self):

        self.root = Path("workspace")

        self.root.mkdir(exist_ok=True)

        self.folders = [
            "research",
            "reports",
            "projects",
            "videos",
            "finance",
            "memory",
            "logs",
            "temp",
        ]

        for folder in self.folders:
            (self.root / folder).mkdir(
                parents=True,
                exist_ok=True,
            )

    def path(self, folder: str) -> Path:

        return self.root / folder

    def write(
        self,
        folder: str,
        filename: str,
        content: str,
    ) -> Path:

        file_path = self.path(folder) / filename

        file_path.write_text(
            content,
            encoding="utf-8",
        )

        return file_path

    def timestamp(self):

        return datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )