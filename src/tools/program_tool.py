import subprocess
import os

from src.tools.base_tool import BaseTool


class ProgramTool(BaseTool):

    def __init__(self):
        super().__init__(
            name="Program Tool",
            description="Program açma aracı",
            requires_confirmation=True,
        )

    def execute(self, **kwargs):

        program = kwargs.get("program")

        if not program:
            return "Program belirtilmedi."

        try:

            programs = {
                "notepad": "notepad.exe",
                "hesap makinesi": "calc.exe",
                "calculator": "calc.exe",
                "paint": "mspaint.exe",
                "cmd": "cmd.exe",
                "powershell": "powershell.exe",
                "explorer": "explorer.exe",
            }

            if program.lower() in programs:

                subprocess.Popen(programs[program.lower()])

                return f"{program} açıldı."

            subprocess.Popen(program)

            return f"{program} açıldı."

        except Exception as e:

            return f"Hata: {e}"