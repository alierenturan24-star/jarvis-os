from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from src.jobs.task import Task

if TYPE_CHECKING:
    # Yalnızca statik tip kontrolü için -- ``from __future__ import
    # annotations`` sayesinde çalışma zamanında hiç değerlendirilmez, bu
    # yüzden ``target_resolver.py``'ye/``src.strategy``'ye çalışma zamanı
    # bağımlılığı (ve dairesel import riski) YOKTUR.
    from src.mission.recovery import MissionRecoveryReport
    from src.mission.target_resolver import Target
    from src.strategy.execution_planner import ExecutionPlan, SelfCheckReport
    from src.strategy.models import AIStrategyPlan


class MissionStatus(str, Enum):
    """Bir Mission'ın yaşam döngüsü boyunca alabileceği durumlar."""

    CREATED = "created"
    PLANNED = "planned"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MissionType(str, Enum):
    """11 mission türü (Sprint 13 kapsamı)."""

    RESEARCH = "research"
    FINANCE = "finance"
    YOUTUBE = "youtube"
    SOCIAL_MEDIA = "social_media"
    CODE = "code"
    GITHUB = "github"
    BROWSER = "browser"
    SECURITY = "security"
    LEARNING = "learning"
    AUTOMATION = "automation"
    MEDIA = "media"
    # Sprint 17: GitHub'ın dışındaki AI ekosistemini (yeni model/araç/
    # agent-framework duyuruları) tarayan mission türü. Yeni bir Mission
    # SİSTEMİ İCAT ETMEZ -- mevcut MissionType enum'ına eklenen tek bir
    # üye (bkz. src/mission/department.py: ai_discovery departmanı).
    AI_DISCOVERY = "ai_discovery"


@dataclass
class ResourcePlan:
    """"Kaynak planı" — Sprint 13 kapsamında yalnızca ALANLAR hazırlanır;
    gerçek bir Resource Manager (ölçüm/uygulama) henüz YAZILMAZ. Değerler
    kaba, department sayısına dayalı SEZGİSEL tahminlerdir — gerçek
    ölçüm değildir.
    """

    estimated_cpu: float = 0.0        # çekirdek-saniye (kaba tahmin)
    estimated_memory: float = 0.0     # MB (kaba tahmin)
    estimated_tokens: int = 0         # LLM token tahmini (kaba tahmin)
    estimated_cost: float = 0.0       # USD (kaba tahmin)


@dataclass
class Mission:
    """JARVIS'in TEK bir görev yerine yürüttüğü, birden çok departmana
    dağıtılan üst düzey bir hedefin temsili.

    Zincir: ``Mission`` → (``DepartmentOrchestrator.create_tasks``) →
    ``TaskPlan`` (``src.core.task_plan.TaskPlan``) → (``PlanExecutor``)
    → ``PlanExecutionReport``.
    """

    title: str
    description: str = ""
    goal: str = ""
    mission_type: MissionType = MissionType.RESEARCH

    # Sprint 31A: Mission oluşturulurken TargetResolver ile BİR KEZ
    # çözümlenen, tüm departmanlarca paylaşılan hedef (bkz.
    # ``target_resolver.py``). ``None`` = henüz çözümlenmedi (geriye
    # dönük uyumluluk: Mission'ı doğrudan oluşturan eski/test kodu için).
    target: "Optional[Target]" = None

    # Sprint 35: AI Strategy Engine'in (Sprint 34, bkz. ``src.strategy``)
    # bu mission için ürettiği plan -- Mission oluşturulurken BİR KEZ
    # (``MissionEngine.create_mission``) hesaplanır ve CEO raporunda
    # (bkz. ``report_builder._ai_strategy_section``) gösterilir. ``None``
    # = plan üretilemedi (ör. hiçbir AI sağlayıcısı kullanılabilir değil)
    # veya Mission'ı doğrudan (MissionEngine atlanarak) oluşturan eski/
    # test kodu -- KURAL gereği AI Strategy hiçbir görevi ÇALIŞTIRMAZ, bu
    # yüzden eksik olması Mission yürütmesini ETKİLEMEZ.
    ai_strategy: "Optional[AIStrategyPlan]" = None

    # Sprint 36: Execution Planner'ın (bkz. ``src.strategy.execution_planner``)
    # ``ai_strategy``'den TÜRETTİĞİ, okunabilir yürütme zinciri (Görev ->
    # AI seçimi -> Tool seçimi -> Department zinciri -> Risk -> Maliyet).
    # ``MissionEngine.create_mission`` içinde BİR KEZ hesaplanır. Gerçek
    # dispatch sırasını/mimarisini DEĞİŞTİRMEZ -- yalnızca ANLATIM içindir.
    execution_plan: "Optional[ExecutionPlan]" = None

    # Sprint 36: Mission TAMAMLANDIKTAN SONRA (``CEO.dispatch_mission``
    # içinde) hesaplanan self-check (başarı oranı, eksik bilgi, tekrar
    # araştırılması gereken yer, Sprint 35'in self-improvement'ı). ``None``
    # = mission henüz dispatch edilmedi veya değerlendirme başarısız oldu.
    self_check: "Optional[SelfCheckReport]" = None

    # Sprint 42 (AUTONOMOUS GOAL EXECUTION): dispatch SONRASI görevlerden
    # biri BAŞARISIZ olursa ``CEO.dispatch_mission`` içinde hesaplanan
    # kurtarma denemesi raporu (bkz. ``src.mission.recovery``). ``None`` =
    # hiç başarısız görev yoktu (kurtarma hiç TETİKLENMEDİ) veya Mission
    # henüz dispatch edilmedi.
    recovery: "Optional[MissionRecoveryReport]" = None

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    priority: int = 1
    status: MissionStatus = MissionStatus.CREATED
    created_at: datetime = field(default_factory=datetime.now)
    deadline: Optional[datetime] = None

    departments: list[str] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)

    progress: float = 0.0          # 0-100, TaskPlan.summary()'den türetilir
    confidence: float = 0.0        # 0-100, departman "olgunluğuna" dayalı sezgisel
    estimated_duration: float = 0.0  # dakika, kaba sezgisel tahmin

    required_resources: ResourcePlan = field(default_factory=ResourcePlan)
    risk_level: str = "LOW"        # LOW | MEDIUM | HIGH | CRITICAL

    success_criteria: list[str] = field(default_factory=list)

    # Concrete user-goal outputs are separate from successful department
    # execution. Paths are explicit outputs reported by mission/tasks; no
    # workspace or disk-wide scan is performed.
    completion_requirements: tuple = ()
    artifact_paths: list[str] = field(default_factory=list)
    constraints: tuple[str, ...] = ()
    output_preferences: tuple[str, ...] = ()
    context: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    current_capabilities: tuple[str, ...] = ()
    capability_gaps: tuple[str, ...] = ()
    discovery_required: bool = False
    # Candidates survive the whole mission so discovery output can be handed
    # to evaluation/sandbox/integration instead of being rediscovered (or
    # lost) during recovery.
    capability_candidates: list[dict] = field(default_factory=list)

    # Sprint: generic capability-requirement resolution (src.capabilities.
    # requirement/resolution). A finer-grained, REQUIRED/OPTIONAL/ALTERNATIVE
    # -aware view computed ALONGSIDE the coarse department-level
    # required_capabilities/capability_gaps above -- neither replaces the
    # other, and recover_mission's reactive ladder is unchanged. Empty tuples
    # = a mission type with no fine-grained table entry yet (honest
    # "not modeled"), or MissionEngine computed it without a matching
    # mission type. Stored as plain dicts (dataclasses.asdict-style),
    # matching how capability_candidates is already stored.
    capability_requirements: tuple[dict, ...] = ()
    capability_resolutions: tuple[dict, ...] = ()

    # JARVIS PRIORITY (Control Center explicit delegation hints): optional,
    # ALLOWLISTED execution hints threaded from the HTTP layer
    # (``ControlCenterService.submit_command`` -> ``JarvisRuntime.execute``
    # -> ``Jarvis.chat``/``_run_mission`` -> ``CEO.run_mission``/
    # ``create_mission`` -> here). Only ``preferred_ai_provider``/
    # ``coding_mode`` are ever placed in this dict (validated against the
    # real ``ProviderManager`` registry + an explicit mode allowlist in
    # ``ControlCenterService``) -- arbitrary client metadata never reaches
    # this field. Empty dict = no explicit hint (old callers/tests
    # unaffected). Only ``department_orchestrator.create_tasks`` reads this,
    # and only for the "coding" department.
    execution_hints: dict = field(default_factory=dict)
