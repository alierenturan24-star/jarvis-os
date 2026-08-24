from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.core.goal_engine import GoalEngine
from src.core.task_plan import TaskPlan
from src.mission.department import classify_mission_type
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.models import Mission, MissionStatus, ResourcePlan
from src.mission.task_criticality import critical_failures
from src.mission.completion import infer_completion_requirements
from src.mission.recovery import plan_needs_recovery, recover_mission
from src.mission.goal_spec import parse_goal_spec
from src.mission.target_resolver import TargetResolver
from src.strategy.execution_planner import build_execution_plan
from src.strategy.strategy_engine import AIStrategyEngine
from src.providers.provider_manager import ProviderManager
from src.media.renderer import has_production_media_capability
from src.capabilities.capability_registry import CapabilityRegistry


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
        strategy_engine: Optional[AIStrategyEngine] = None,
        capability_registry: Optional[CapabilityRegistry] = None,
    ) -> None:
        self.goal_engine = goal_engine or GoalEngine()
        self.orchestrator = orchestrator or DepartmentOrchestrator()
        # Sprint 31A: tüm departmanların paylaşacağı Target'ı Mission
        # oluşturulurken BİR KEZ üretmek için (bkz. create_mission).
        self.target_resolver = TargetResolver()
        # Sprint 35: Sprint 34'te hazırlanan AI Strategy Engine'i CANLI
        # akışa bağlar -- ikinci bir DepartmentOrchestrator ÖRNEĞİ
        # OLUŞTURULMAZ, ``self.orchestrator`` ile AYNI örnek paylaşılır
        # (böylece AIStrategyEngine.plan()'in department seçimi, GERÇEK
        # dispatch'in department seçimiyle her zaman AYNI kalır).
        self.strategy_engine = strategy_engine or AIStrategyEngine(orchestrator=self.orchestrator)
        self.capability_registry = capability_registry or CapabilityRegistry()

    # --- Mission üretimi -----------------------------------------------------------

    def create_mission(
        self,
        request: str,
        *,
        priority: int = 1,
        deadline: Optional[datetime] = None,
        execution_hints: Optional[dict] = None,
    ) -> Mission:
        """Bir kullanıcı isteğinden ``Mission`` üretir: hedefi
        ``GoalEngine``'e kaydeder/eşler, mission türünü sınıflandırır,
        departmanları seçer ve kaynak/risk/güven tahminlerini doldurur."""

        request = (request or "").strip()
        if not request:
            raise ValueError("Mission oluşturmak için boş olmayan bir istek gerekli.")

        spec = parse_goal_spec(request)
        goal = self._resolve_goal(spec.goal)
        # Context clauses are still positive goal semantics; only constraints
        # and output formatting are excluded from routing.  Using merely the
        # first sentence silently erased capability verbs such as compare,
        # backtest and OOS from long-form goals.
        semantic_goal = ". ".join((spec.goal, *spec.context))
        mission_type = classify_mission_type(semantic_goal)
        departments = self.orchestrator.select_departments(semantic_goal)
        # Sprint 31A: TargetResolver YALNIZCA BURADA, bir kez çalışır --
        # tüm departmanlar aynı sonucu paylaşır (bkz.
        # department_orchestrator.create_tasks -> task.metadata["target"]).
        target = self.target_resolver.resolve(semantic_goal, mission_type=mission_type)

        required = list(departments)
        # The existing media department produces a content plan, not a real
        # video/audio artifact. Represent that honest delta explicitly and use
        # the existing discovery worker to seek only the missing capability.
        preview_requirements = infer_completion_requirements(semantic_goal, departments)
        wants_media_artifact = any(item.kind == "artifact" for item in preview_requirements)
        if wants_media_artifact:
            required.append("media_artifact")
        required_capabilities = tuple(dict.fromkeys(required))
        current_capability_names = [
            name for name in departments
            if name in self.orchestrator.departments and self.orchestrator.departments[name].maturity >= 0.5
        ]
        if wants_media_artifact and has_production_media_capability(semantic_goal):
            current_capability_names.append("media_artifact")
        registry_candidates: list[dict] = []
        for required_name in required_capabilities:
            selected = self.capability_registry.select(required_name)
            if selected:
                current_capability_names.append(required_name)
                registry_candidates.extend(dict(item) if isinstance(item, dict) else {
                    "capability_id": item.id, "name": item.name, "category": item.category,
                    "status": item.status, "available": item.available,
                } for item in selected)
        current_capabilities = tuple(dict.fromkeys(current_capability_names))
        capability_gaps = tuple(name for name in required_capabilities if name not in current_capabilities)

        mission = Mission(
            title=request,
            # Preserve the complete user message for audit/reporting. Routing
            # and task planning use ``goal`` so constraints never become jobs.
            description=request,
            goal=goal,
            mission_type=mission_type,
            target=target,
            priority=priority,
            status=MissionStatus.CREATED,
            deadline=deadline,
            departments=departments,
            constraints=spec.constraints,
            output_preferences=spec.output_preferences,
            context=spec.context,
            required_capabilities=required_capabilities,
            current_capabilities=current_capabilities,
            capability_gaps=capability_gaps,
            discovery_required=bool(capability_gaps),
            capability_candidates=registry_candidates,
            execution_hints=dict(execution_hints) if execution_hints else {},
        )

        # Sprint 35: AI Strategy Engine, Mission ÇALIŞMADAN ÖNCE bir plan
        # üretir (KURAL: hiçbir görevi ÇALIŞTIRMAZ -- yalnızca ZATEN
        # hesaplanmış ``select_departments``/``CostOptimizer`` kararlarını
        # okur, bkz. ``src.strategy.strategy_engine``). Planlama
        # başarısız olursa (ör. hiçbir AI sağlayıcısı kullanılabilir
        # değil) Mission oluşturmayı KESMEZ -- ``ai_strategy`` ``None``
        # kalır, mevcut Mission/Department yürütmesi AYNEN devam eder
        # (bkz. Sprint 35 kısıtı: "mevcut mimari... bozulmayacak").
        try:
            mission.ai_strategy = self.strategy_engine.plan(request)
        except Exception:
            mission.ai_strategy = None

        mission.confidence = self._estimate_confidence(departments)
        mission.risk_level = self._estimate_risk(mission.confidence)
        mission.estimated_duration = self._estimate_duration(departments)
        mission.required_resources = self._estimate_resources(departments)
        mission.success_criteria = self._build_success_criteria(mission)
        # Constraints are excluded from routing, but safety outcomes such as
        # publish/real-money-not-used remain completion evidence.
        mission.completion_requirements = infer_completion_requirements(request, departments)

        # Sprint 36: Execution Planner, AI Strategy'nin planından okunabilir
        # bir yürütme zinciri türetir (KURAL: hiçbir görevi ÇALIŞTIRMAZ,
        # yeni bir seçim mantığı İCAT ETMEZ -- bkz. execution_planner.py).
        try:
            mission.execution_plan = build_execution_plan(mission.ai_strategy, mission.risk_level)
        except Exception:
            mission.execution_plan = None

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
        if plan_needs_recovery(plan, mission):
            mission.recovery = recover_mission(
                mission, plan, provider_manager=ProviderManager(),
            )
            completion_pending = plan_needs_recovery(plan, mission)
            if completion_pending:
                mission.status = (
                    MissionStatus.BLOCKED if mission.recovery.blocked else MissionStatus.INCOMPLETE
                )
            elif not critical_failures(plan):
                mission.status = MissionStatus.COMPLETED
            execution_report.success = mission.status == MissionStatus.COMPLETED
            mission.progress = self.orchestrator._compute_progress(plan)
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
