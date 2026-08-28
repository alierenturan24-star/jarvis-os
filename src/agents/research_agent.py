import re

from src.agents.base_agent import BaseAgent
from src.planner.task import Task
from src.research.local_code_manager import LocalCodeManager
from src.research.local_code_search import is_local_code_query
from src.research.manager import ResearchManager
from src.research.opportunity import build_selected_opportunity


class ResearchAgent(BaseAgent):

    def __init__(self) -> None:

        super().__init__("Research Agent")
        self.manager = ResearchManager()
        # Sprint 41 (LOCAL CODE INTELLIGENCE): JARVIS kendi kod tabanı
        # hakkında sorulduğunda WEB araması YERİNE bunu kullanır -- bkz.
        # ``execute()``. İkinci bir Research sistemi İCAT EDİLMEDİ, yalnızca
        # bu departmanın karar noktasına bir dal EKLENDİ.
        self.local_code_manager = LocalCodeManager()

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

        preferred_provider = getattr(task, "metadata", {}).get("preferred_ai_provider")

        # Sprint 41 (LOCAL CODE INTELLIGENCE / TOOL-FIRST): metinde
        # JARVIS'in KENDİ kod tabanında GERÇEKTEN var olan bir sınıf/modül
        # adı geçiyorsa (ör. "CostOptimizer"), WEB araması YAPILMAZ --
        # yerel dosyalar okunur. Sinyal hardcoded bir cümle listesi
        # DEĞİL, doğrudan ZATEN VAR OLAN ``scan_jarvis_architecture``
        # indeksinden gelir (bkz. ``is_local_code_query``).
        if is_local_code_query(command):
            return self.local_code_manager.analyze(command, preferred_provider=preferred_provider)

        target = getattr(task, "metadata", {}).get("target")
        requested_name = getattr(target, "requested_name", None)
        query = requested_name or self._clean_query(command)

        if not query:
            return "Araştırılacak konu belirtilmedi."

        force_refresh = any(
            phrase in command.casefold()
            for phrase in [
                "güncelle",
                "yeniden araştır",
            ]
        )

        # Sprint 35: AI Strategy Engine'in seçtiği provider'ı (varsa,
        # DepartmentOrchestrator.create_tasks -> task.metadata) mevcut
        # ResearchManager/Summarizer/ProviderManager zincirine iletir --
        # yeni bir provider seçim mantığı İCAT EDİLMEZ.
        research_kwargs = {
            "topic": query,
            "force_refresh": force_refresh,
            "preferred_provider": preferred_provider,
        }
        if requested_name:
            research_kwargs["evidence_only"] = True
        result = self.manager.research(**research_kwargs)

        # Round 5 repair: when this research call exists to select a
        # content opportunity FOR a downstream media task (``market_context``
        # is set by department_orchestrator.py only for that implicit
        # topic-discovery case), expose a compact, structured, traceable
        # handoff into ``task.metadata["report"]`` -- the SAME convention
        # github/evaluation/sandbox/integration already use for structured
        # results (see report_builder.py) -- instead of forcing the
        # consumer (MediaAgent) to re-parse or silently ignore the long
        # natural-language report.
        market_context = getattr(task, "metadata", {}).get("market_context")
        if market_context is not None:
            record = self.manager.knowledge.find_research(query)
            opportunity = build_selected_opportunity(
                topic=query,
                location_or_market=market_context,
                summary=str(record.get("summary", "")) if record else "",
                sources=record.get("sources", []) if record else (),
                created_at=str(record.get("created_at", "")) if record else "",
            )
            task.metadata["report"] = opportunity.as_dict()

        return result
