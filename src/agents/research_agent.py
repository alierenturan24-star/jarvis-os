import re

from src.agents.base_agent import BaseAgent
from src.planner.task import Task
from src.research.manager import ResearchManager


class ResearchAgent(BaseAgent):

    def __init__(self) -> None:

        super().__init__("Research Agent")
        self.manager = ResearchManager()

    @staticmethod
    def _clean_query(text: str) -> str:

        text = text.strip()

        phrases = [
            "araştırır mısın",
            "web araması yap",
            "web araması",
            "yeniden araştır",
            "araştır",
            "incele",
            "güncelle",
        ]

        lowered = text.casefold()

        # Sprint 21 düzeltmesi: düz .replace() bir kelimenin İÇİNDE geçen
        # bir öbeği de siliyordu -- ör. "araştır", "araştırma" kelimesinin
        # içinden çıkarılınca geriye anlamsız "ma" kalıyordu ("browser
        # kullanarak ma yap." gibi bozuk sorgular; bkz. Sprint 20 Beta Test
        # raporu, madde 9). Türkçe eklemeli yapısı nedeniyle kelime SINIRI
        # (\b) ile başlayıp, öbekten sonra gelen tüm bitişik harfleri
        # (\w*) -- yani ekleri -- birlikte kaldırıyoruz; böylece "araştır"
        # öbeği "araştırma"/"araştırıyorum" gibi türetilmiş kelimelerin
        # TAMAMINI siler, ortada anlamsız bir kalıntı bırakmaz.
        for phrase in phrases:
            lowered = re.sub(rf"\b{re.escape(phrase)}\w*", "", lowered)

        # Kaldırılan öbeklerin bıraktığı ard arda boşlukları tek boşluğa
        # indirger (ör. "browser kullanarak  yap." -> "browser kullanarak yap.").
        lowered = re.sub(r"\s+", " ", lowered)

        return lowered.strip(" :,-").strip()

    def execute(self, task: Task) -> str:

        command = str(
            getattr(task, "target", "")
        )

        query = self._clean_query(command)

        if not query:
            return "Araştırılacak konu belirtilmedi."

        force_refresh = any(
            phrase in command.casefold()
            for phrase in [
                "güncelle",
                "yeniden araştır",
            ]
        )

        return self.manager.research(
            topic=query,
            force_refresh=force_refresh,
        )