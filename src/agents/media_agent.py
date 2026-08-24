import re
import inspect
from src.mission.completion import has_youtube_production_intent

from src.agents.base_agent import BaseAgent
from src.media.manager import MediaManager
from src.planner.task import Task

# Sprint 39: mission metninden konuyu ve hedef süreyi çıkarır. Türkçe'de
# "X konusunda" kalıbı, bir istekte KONUYU işaret eden en güvenilir/dar
# sinyal olduğu için (bkz. Sprint 39 kabul testi: "Bitcoin neden düştü
# KONUSUNDA 60 saniyelik bir YouTube Shorts hazırla") kullanılıyor -- yeni
# bir genel NLP çözümleyici İCAT EDİLMEDİ, ``FinanceAgent``/``ResearchAgent``
# ile AYNI dar regex-tabanlı çıkarım deseni izlendi. Kalıp bulunamazsa ham
# metin (mevcut research/ai_discovery davranışıyla AYNI, bkz. Sprint 37/38)
# olduğu gibi konu olarak kullanılır.
_TOPIC_PATTERN = re.compile(r"^(.*?)\s+konusunda\b", re.IGNORECASE)
_DURATION_PATTERN = re.compile(r"(\d+)\s*saniye")
_DEFAULT_DURATION_SECONDS = 60
_CHANNEL_PATTERN = re.compile(r"\[WORKFORCE_CHANNEL:([a-z0-9-]+)\]", re.IGNORECASE)


class MediaAgent(BaseAgent):
    """``media`` departmanını (Sprint 39) ``MediaManager``'a bağlar.

    ``FinanceAgent``/``ResearchAgent`` ile AYNI desen: görev metnini
    ayrıştırır, AI Strategy Engine'in (varsa) seçtiği provider'ı iletir,
    gerçek işi ZATEN VAR OLAN Manager'a devreder."""

    def __init__(self) -> None:
        super().__init__("Media Agent")
        self.manager = MediaManager()

    @staticmethod
    def _extract_topic(text: str) -> str:
        match = _TOPIC_PATTERN.search(text)
        if match:
            return match.group(1).strip(" ,.-")
        return text.strip()

    @staticmethod
    def _extract_duration(text: str) -> int:
        match = _DURATION_PATTERN.search(text)
        if match:
            return int(match.group(1))
        return _DEFAULT_DURATION_SECONDS

    def execute(self, task: Task) -> str:
        command = str(getattr(task, "target", ""))

        topic = self._extract_topic(command)
        duration = self._extract_duration(command)

        preferred_provider = getattr(task, "metadata", {}).get("preferred_ai_provider")

        channel_match = _CHANNEL_PATTERN.search(command)
        if channel_match:
            self.manager.set_channel_scope(channel_match.group(1))
            task.metadata["channel_id"] = channel_match.group(1)

        produce_artifact = has_youtube_production_intent(command)
        plan_kwargs = {
            "topic": topic,
            "duration_seconds": duration,
            "preferred_provider": preferred_provider,
        }
        if produce_artifact and "produce_artifact" in inspect.signature(self.manager.plan).parameters:
            plan_kwargs["produce_artifact"] = True
        result = self.manager.plan(**plan_kwargs)
        if "SENARYO" in result and "SAHNELER" in result:
            task.metadata["youtube_content_plan"] = True
        if self.manager.last_artifact_path:
            task.metadata["artifact_path"] = self.manager.last_artifact_path
        if self.manager.last_production_record:
            task.metadata["youtube_production"] = self.manager.last_production_record
            task.metadata["learning_persisted"] = True
        if getattr(self.manager, "last_capability_gap", None):
            task.metadata["capability_gap"] = self.manager.last_capability_gap
        return result
