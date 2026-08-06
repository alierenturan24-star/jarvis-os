from __future__ import annotations

from typing import Optional

from src.core.plan_executor import PlanExecutionReport, PlanExecutor
from src.core.task_plan import TaskPlan
from src.jobs.job_manager import JobManager
from src.jobs.task import Task
from src.mission.department import (
    DEFAULT_DEPARTMENTS,
    DEFAULT_DEPARTMENTS_BY_MISSION_TYPE,
    Department,
    classify_mission_type,
)
from src.mission.department_adapters import DepartmentAdapterRegistry
from src.mission.models import Mission, MissionStatus

# Sprint 15: gerçek modüle bağlı görevler için (ağ/klon içeren, sınırsız
# beklemeye BIRAKILMAMASI gereken) üst sınır. Handler'sız (henüz
# bağlanmamış) departmanları ETKİLEMEZ -- onlar zaten anında "handler
# tanımlı değil" ile başarısız olur.
#
# Sprint 19 (Beta Stabilization) düzeltmesi: 45 sn, research/finance gibi
# gerçek bir Ollama LLM çağrısı içeren departmanlar için YETERSİZDİ --
# ölçüldü (bkz. Sprint 19 raporu): tek bir yerel Ollama çağrısı bu
# donanımda 45-100+ saniye sürebiliyor (gereksiz/kaldırılabilir bir
# bekleme DEĞİL -- gerçek model çıkarım süresi). 45 sn'nin YETERSİZ
# olduğu ölçüldükten sonra üst sınır, gözlenen en kötü durumu (~100 sn)
# güvenli bir marjla karşılayacak şekilde yükseltildi.
DEPARTMENT_TASK_TIMEOUT_SECONDS = 150.0

# Sprint 19 düzeltmesi: "browser" departmanının task action'ı hep sabit
# "dispatch" kalıyordu -- BrowserAgent bu action'ı TANIMADIĞI için gerçek
# BrowserTool eylemi hiçbir zaman tetiklenmiyor, hep zararsız ama YANLIŞ
# bir "desteklenmeyen işlem" mesajı dönüyordu (bkz. Sprint 18 canlı test
# raporu). "search", BrowserAgent'ın zaten TANIDIĞI (değiştirilmemiş) bir
# eylem -- metadata'da "query" verilmezse BrowserAgent zaten task.target'ı
# sorgu olarak kullanır (bkz. src/agents/browser_agent.py, değiştirilmedi).
DEPARTMENT_ACTIONS: dict[str, str] = {"browser": "search"}
DEFAULT_DEPARTMENT_ACTION = "dispatch"


class DepartmentOrchestrator:
    """CEO katmanının, işi KENDİSİ yapmadan departmanlara DAĞITAN parçası.

    Bu sınıf hiçbir görevi doğrudan çalıştırmaz: ``dispatch()`` gerçek
    Execution Engine'e (``src.core.task_plan.TaskPlan`` +
    ``src.core.plan_executor.PlanExecutor``, Sprint 8'de sertleştirilmiş
    mevcut sistem) devreder. Yeni bir yürütme motoru İCAT ETMEZ.
    """

    def __init__(self, adapters: DepartmentAdapterRegistry | None = None) -> None:
        self.departments: dict[str, Department] = {}
        for department in DEFAULT_DEPARTMENTS:
            self.register_department(
                department.name, department.description, department.keywords, department.maturity,
            )
        # Sprint 15: department -> gerçek modül bağlantısı (bkz.
        # ``department_adapters.py``). ``create_tasks()`` bunu kullanarak
        # her görevin ``handler``'ını GERÇEK bir sınıfa bağlar.
        self.adapters = adapters or DepartmentAdapterRegistry()

    # --- Kayıt -----------------------------------------------------------------

    def register_department(
        self,
        name: str,
        description: str = "",
        keywords: Optional[list[str]] = None,
        maturity: float = 0.5,
    ) -> Department:
        department = Department(
            name=name, description=description, keywords=list(keywords or []), maturity=maturity,
        )
        self.departments[name] = department
        return department

    # --- Seçim -----------------------------------------------------------------

    def select_departments(self, text: str) -> list[str]:
        """Kullanıcı isteğini önce bir ``MissionType``'a sınıflandırır,
        o türün KANONİK departman demetini taban alır, sonra metindeki
        ek departman-özel anahtar kelimelerle (varsa) zenginleştirir."""

        mission_type = classify_mission_type(text)
        bundle = list(DEFAULT_DEPARTMENTS_BY_MISSION_TYPE.get(mission_type, ()))

        lowered = (text or "").lower()
        for name, department in self.departments.items():
            if name in bundle:
                continue
            if any(keyword in lowered for keyword in department.keywords):
                bundle.append(name)

        return bundle

    # --- Görev üretimi -------------------------------------------------------------

    def create_tasks(self, mission: Mission) -> list[Task]:
        """Mission'ın seçilmiş her departmanı için BAĞIMSIZ (birbirine
        depends_on ile bağlı olmayan — departmanlar paralel çalışır) bir
        ``Task`` üretir. Sprint 15: her görevin ``handler``'ı, o
        departmanın arkasında GERÇEK bir alt sistemi olup olmadığına göre
        ``DepartmentAdapterRegistry`` üzerinden bağlanır (varsa gerçek
        modül; yoksa ``None`` -- ``JobManager`` bunu önceki davranışla
        AYNI şekilde "handler tanımlı değil" ile raporlar)."""

        tasks: list[Task] = []

        for department_name in mission.departments:
            department = self.departments.get(department_name)
            description = department.description if department else "Kayıtlı olmayan departman."
            handler = self.adapters.resolve(department_name)

            tasks.append(Task(
                title=f"[{department_name}] {mission.title}",
                agent=department_name,
                action=DEPARTMENT_ACTIONS.get(department_name, DEFAULT_DEPARTMENT_ACTION),
                target=mission.description or mission.title,
                priority=mission.priority,
                handler=handler,
                timeout_seconds=DEPARTMENT_TASK_TIMEOUT_SECONDS if handler is not None else None,
                metadata={
                    "mission_id": mission.id,
                    "department": department_name,
                    "department_description": description,
                    # Sprint 21 düzeltmesi: GitHub kategori tespiti serbest
                    # metin eşleşmesine güvenince hep "ai agent"a düşüyordu
                    # (Türkçe metin İngilizce kategori adlarını nadiren
                    # içerir). Adaptörlerin (bkz. department_adapters.py
                    # ``resolve_search_category``) MissionType'a göre daha
                    # isabetli bir kategori seçebilmesi için mission türü
                    # de veriliyor.
                    "mission_type": mission.mission_type,
                },
            ))

        return tasks

    # --- Dağıtım (gerçek Execution Engine'e devir) --------------------------------

    def dispatch(
        self,
        mission: Mission,
        plan: TaskPlan,
        *,
        cancel_on_failure: bool = False,
    ) -> PlanExecutionReport:
        """Görevleri KENDİSİ ÇALIŞTIRMAZ — ``plan``'ı gerçek Execution
        Engine'e (``PlanExecutor`` + ``JobManager``) devreder.

        Sprint 15: ``create_tasks()`` artık her görevin ``handler``'ını
        (varsa) gerçek bir modüle bağlıyor (bkz. ``department_adapters.py``).
        Arkasında GERÇEK bir alt sistemi olan departmanlar (github,
        evaluation, sandbox, integration, research, finance, browser)
        gerçekten çalışır; hâlâ karşılığı olmayanlar (ör. automation,
        media, social_media, security, learning, coding) öncekiyle AYNI
        şekilde "handler tanımlı değil" ile başarısız tamamlanır — yeni
        bir AI/worker İCAT EDİLMEDİ (bkz. rapor).
        """

        mission.status = MissionStatus.DISPATCHED
        executor = PlanExecutor(JobManager(), cancel_on_failure=cancel_on_failure)
        report = executor.run(plan)

        mission.status = MissionStatus.COMPLETED if report.success else MissionStatus.FAILED
        mission.progress = self._compute_progress(plan)

        return report

    # --- Sonuç toplama --------------------------------------------------------------

    def collect_results(self, plan: TaskPlan) -> dict:
        return {
            "summary": plan.summary(),
            "results": [
                {
                    "department": task.agent,
                    "status": task.status.value,
                    "attempts": task.attempts,
                    "result": task.result,
                    "error": task.error,
                }
                for task in plan.all_tasks()
            ],
        }

    # --- Rapor -------------------------------------------------------------------

    def build_report(
        self,
        mission: Mission,
        plan: TaskPlan,
        execution_report: PlanExecutionReport,
    ) -> dict:
        collected = self.collect_results(plan)

        return {
            "mission_id": mission.id,
            "title": mission.title,
            "mission_type": mission.mission_type.value,
            "status": mission.status.value,
            "departments": mission.departments,
            "progress": mission.progress,
            "confidence": mission.confidence,
            "risk_level": mission.risk_level,
            "task_summary": collected["summary"],
            "department_results": collected["results"],
            "execution_success": execution_report.success,
            "executed_count": len(execution_report.executed),
            "cancelled_count": len(execution_report.cancelled),
        }

    # --- Dahili --------------------------------------------------------------------

    @staticmethod
    def _compute_progress(plan: TaskPlan) -> float:
        summary = plan.summary()
        total = sum(summary.values())
        if total == 0:
            return 0.0
        finished = summary.get("completed", 0) + summary.get("failed", 0) + summary.get("cancelled", 0)
        return round(100.0 * finished / total, 1)
