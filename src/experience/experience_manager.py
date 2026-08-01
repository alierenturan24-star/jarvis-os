import json
from pathlib import Path

from src.experience.experience import Experience


class ExperienceManager:

    FILE = Path("data/experience.json")

    def __init__(self):

        self.FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if not self.FILE.exists():

            self.FILE.write_text(
                "[]",
                encoding="utf-8",
            )

    def save(self, exp: Experience):

        data = json.loads(
            self.FILE.read_text(
                encoding="utf-8"
            )
        )

        data.append({

            "name": exp.name,

            "version": exp.version,

            "success": exp.success,

            "score": exp.score,

            "notes": exp.notes,

            "created_at": str(exp.created_at),

        })

        self.FILE.write_text(

            json.dumps(
                data,
                indent=4,
                ensure_ascii=False,
            ),

            encoding="utf-8",
        )

    def all(self):

        return json.loads(

            self.FILE.read_text(
                encoding="utf-8"
            )
        )