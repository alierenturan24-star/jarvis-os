from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.core.goal_engine import GoalEngine
from src.core.task_plan import TaskPlan
from src.mission.department import classify_mission_type
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.models import Mission, MissionStatus, ResourcePlan


class MissionEngine:
    """Mevcut ``GoalEngine``'i (``src.core.goal_engine`` — YENİDEN
    YAZILMADI) kullanarak kullanıcı isteklerini ``Mission``'a çevirir ve
    ``Mission`` → ``TaskPlan`` (``src.core.task_plan.TaskPlan``, Sprint
    8'in sertleştirilmiş Execution zinciri) → ``PlanExecutor`` bağlantısını
    kurar. Yeni bir hedef/yürütme motoru İCAT ETMEZ.
    """

    def __init__(
        self,
        goal_engine: Optional[GoalEngine] = None,
        orchestrator: Optional[DepartmentOrchestrator] = None,
    ) -> None:
        self.goal_engine = goal_engine or GoalEngine()
        self.orchestrator = orchestrator or DepartmentOrchestrator()

    # --- Mission üretimi -----------------------------------------------------------

    def create_mission(
        self,
        request: str,
        *,
        priority: int = 1,
        deadline: Optional[datetime] = None,
    ) -> Mission:
        """Bir kullanıcı isteğinden ``Mission`` üretir: hedefi
        ``GoalEngine``'e kaydeder/eşler, mission türünü sınıflandırır,
        departmanları seçer ve kaynak/risk/güven tahminlerini doldurur."""

        request = (request or "").strip()
        if not request:
            raise ValueError("Mission oluşturmak için boş olmayan bir istek gerekli.")

        goal = self._resolve_goal(request)
        mission_type = classify_mission_type(request)
        departments = self.orchestrator.select_departments(request)

        mission = Mission(
            title=request,
            description=request,
            goal=goal,
            mission_type=mission_type,
            priority=priority,
            status=MissionStatus.CREATED,
            deadline=deadline,
            departments=departments,
        )

        mission.confidence = self._estimate_confidence(departments)
        mission.risk_level = self._estimate_risk(mission.confidence)
        mission.estimated_duration = self._estimate_duration(departments)
        mission.required_resources = self._estimate_resources(departments)
        mission.success_criteria = self._build_success_criteria(mission)

        return mission

    # --- Mission -> TaskPlan ---------------------------------------------------------

    def build_task_plan(self, mission: Mission) -> TaskPlan:
        """``Mission`` → ``TaskPlan`` bağlantısı. Departman görevleri
        birbirinden BAĞIMSIZDIR (``depends_on`` yok) — departmanlar
        paralel/eşzamanlı olarak dağıtılabilir kabul edilir."""

        tasks = self.orchestrator.create_tasks(mission)
        mission.tasks = tasks

        plan = TaskPlan(goal=mission.title)
        for task in tasks:
            plan.add_task(task)

        mission.status = MissionStatus.PLANNED
        return plan

    # --- Uçtan uca: Mission -> TaskPlan -> Execution Engine --------------------------

    def run_mission(
        self,
        request: str,
        *,
        priority: int = 1,
        deadline: Optional[datetime] = None,
        cancel_on_failure: bool = False,
    ) -> tuple[Mission, TaskPlan, dict]:
        """create_mission → build_task_plan → dispatch (gerçek
        PlanExecutor) → build_report zincirinin TAMAMINI tek çağrıda
        çalıştırır. ``(mission, plan, report)`` döner."""

        mission = self.create_mission(request, priority=priority, deadline=deadline)
        plan = self.build_task_plan(mission)
        execution_report = self.orchestrator.dispatch(mission, plan, cancel_on_failure=cancel_on_failure)
        report = self.orchestrator.build_report(mission, plan, execution_report)
        return mission, plan, report

    # --- Dahili: GoalEngine entegrasyonu ------------------------------------------

    def _resolve_goal(self, request: str) -> str:
        """İstekle eşleşen bir hedef zaten ``GoalEngine``'de varsa onu
        kullanır; yoksa YENİ bir hedef olarak ekler (``GoalEngine.add``,
        mevcut API — değiştirilmedi)."""

        normalized = request.strip().lower()
        for existing_goal in self.goal_engine.all():
            if existing_goal.strip().lower() == normalized:
                return existing_goal

        self.goal_engine.add(request)
        return request

    # --- Dahili: kaba sezgisel tahminler (Resource Manager DEĞİL) -------------------

    def _estimate_confidence(self, departments: list[str]) -> float:
        if not departments:
            return 0.0
        maturities = [
            self.orchestrator.departments[name].maturity
            for name in departments
            if name in self.orchestrator.departments
        ]
        if not maturities:
            return 0.0
        return round(100.0 * sum(maturities) / len(maturities), 1)

    @staticmethod
    def _estimate_risk(confidence: float) -> str:
        if confidence >= 80.0:
            return "LOW"
        if confidence >= 50.0:
            return "MEDIUM"
        if confidence >= 25.0:
            return "HIGH"
        return "CRITICAL"

    @staticmethod
    def _estimate_duration(departments: list[str]) -> float:
        # Dakika cinsinden kaba sezgisel: sabit taban + departman başına ek süre.
        return round(10.0 + 5.0 * len(departments), 1)

    @staticmethod
    def _estimate_resources(departments: list[str]) -> ResourcePlan:
        count = max(len(departments), 1)
        tokens = count * 2000
        return ResourcePlan(
            estimated_cpu=round(count * 0.5, 2),
            estimated_memory=round(count * 128.0, 1),
            estimated_tokens=tokens,
            estimated_cost=round(tokens * 0.000002, 4),
        )

    @staticmethod
    def _build_success_criteria(mission: Mission) -> list[str]:
        criteria = [f"{dept} departmanı en az bir sonuç/bulgu üretmeli." for dept in mission.departments]
        criteria.append("TaskPlan döngü/çakışma olmadan (regresyonsuz) tamamlanmalı.")
        return criteria
