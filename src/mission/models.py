from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from src.jobs.task import Task


class MissionStatus(str, Enum):
    """Bir Mission'ın yaşam döngüsü boyunca alabileceği durumlar."""

    CREATED = "created"
    PLANNED = "planned"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
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
