from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.strategy.models import AIStrategyPlan, SelfImprovementReview
from src.utils.llm_utils import is_llm_failure

# Not: ``tools_for_department`` MODÜL SEVİYESİNDE değil, ``build_execution_plan``
# İÇİNDE (fonksiyon-yerel) import edilir -- ``strategy_engine.py`` zincirleme
# olarak ``src.mission.department``/``department_orchestrator``'ı içe
# aktardığı için, bu dosya ``src.mission`` paketi TAM YÜKLENMEDEN (ör.
# doğrudan ``import src.strategy.execution_planner`` ile, ``src.mission``
# üzerinden GELMEDEN) import edilirse dairesel bir içe aktarmaya yol
# açabilir. Fonksiyon-yerel import bu döngüyü KIRAR, davranışı DEĞİŞTİRMEZ.

# Sprint 36 (AUTONOMOUS EXECUTION ENGINE): "Execution Planner" katmanı --
# AI Strategy Engine'in (Sprint 34) ZATEN seçtiği department/tool/AI
# kararlarından okunabilir, SIRALI bir "yürütme zinciri" ANLATIMI üretir.
#
# KURAL (Sprint 34'ün AI Strategy'e uyguladığı kuralın AYNISI, burada da
# geçerli): bu modül hiçbir görevi ÇALIŞTIRMAZ, yeni bir seçim/karar
# mantığı İCAT ETMEZ. Departmanlar hâlâ ``DepartmentOrchestrator`` üzerinden
# birbirinden BAĞIMSIZ/paralel çalışır (bkz. department_orchestrator.py
# docstring'i) -- buradaki "sıra" yalnızca ANLATIM/CEO raporu içindir,
# gerçek dispatch sırasını/mimarisini DEĞİŞTİRMEZ.

# Departmanların CEO raporunda/anlatımında gösterileceği MANTIKSAL sıra.
_STEP_ORDER = (
    "research", "ai_discovery", "github", "browser",
    "evaluation", "sandbox", "integration",
    "finance", "media", "automation", "coding", "social_media", "security", "learning",
)

_STEP_LABELS: dict[str, str] = {
    "research": "Research (web araştırması)",
    "ai_discovery": "AI Discovery (GitHub dışı AI ekosistemi taraması)",
    "github": "GitHub tarama (GitHubIntelligence)",
    "browser": "Browser aç + DOM oku",
    "evaluation": "Evaluation (uygunluk/risk puanlama)",
    "sandbox": "Sandbox (izole statik analiz)",
    "integration": "Integration (entegrasyon planı)",
    "finance": "Finance (piyasa analizi)",
    # Sprint 39: media/automation artık GERÇEK modüllere bağlı (bkz.
    # _TOOLS_FOR_DEPARTMENT) -- etiket bunu yansıtır, ama ikisinin de
    # yalnızca PLAN/ÖNERİ ürettiği (gerçek dosya/kurulum ÜRETMEDİĞİ)
    # dürüstçe belirtilir.
    "media": "Media (YouTube içerik/senaryo planı -- gerçek dosya üretmez)",
    "automation": "Automation (yayın-öncesi kontrol listesi -- gerçek kurulum yapmaz)",
    "coding": "Coding (henüz bağlı değil)",
    "social_media": "Social Media (henüz bağlı değil)",
    "security": "Security (henüz bağlı değil)",
    "learning": "Learning (henüz bağlı değil)",
}

# Sprint 35 kanıtı: yalnızca research/finance gerçekten bir LLM/AI çağrısı
# yapar (ResearchManager/Summarizer, FinanceManager) -- github/evaluation/
# sandbox/integration/browser tamamen deterministiktir (bkz. Sprint 34
# araştırması). Yeni bir AI kullanım analizi İCAT EDİLMEDİ, zaten bilinen
# bu gerçek burada sabit bir kümeye yazıldı.
_USES_AI_DEPARTMENTS = {"research", "finance"}


@dataclass(frozen=True)
class ExecutionStep:
    order: int
    department: str
    label: str
    tool: str
    uses_ai: bool
    ai_note: str
    reason: str


@dataclass(frozen=True)
class ExecutionPlan:
    """Görev ↓ AI seçimi ↓ Tool seçimi ↓ Department zinciri ↓ Risk ↓
    Maliyet -- Sprint 36'nın CEO'ya istediği yürütme planı."""

    steps: tuple[ExecutionStep, ...]
    risk_level: str
    estimated_cost: float
    cost_note: str


def build_execution_plan(
    ai_strategy_plan: Optional[AIStrategyPlan],
    risk_level: str,
) -> Optional[ExecutionPlan]:
    """AI Strategy Engine'in ürettiği plandan (Sprint 34) okunabilir bir
    yürütme zinciri üretir. ``ai_strategy_plan`` ``None``sa (planlama
    başarısız oldu) ``None`` döner -- KURAL: hiçbir görevi çalıştırmaz,
    Mission/Department yürütmesini asla ETKİLEMEZ."""

    if ai_strategy_plan is None:
        return None

    from src.strategy.strategy_engine import tools_for_department

    department_reason = {choice.name: choice.reason for choice in ai_strategy_plan.departments}
    department_names = list(department_reason.keys())

    ordered = sorted(
        department_names,
        key=lambda name: _STEP_ORDER.index(name) if name in _STEP_ORDER else len(_STEP_ORDER),
    )

    steps = []
    for order, name in enumerate(ordered, start=1):
        uses_ai = name in _USES_AI_DEPARTMENTS
        steps.append(
            ExecutionStep(
                order=order,
                department=name,
                label=_STEP_LABELS.get(name, name),
                tool=", ".join(tools_for_department(name)),
                uses_ai=uses_ai,
                ai_note=(
                    f"{ai_strategy_plan.ai_choice.provider} ({ai_strategy_plan.ai_choice.tier})"
                    if uses_ai
                    else "AI gerekmiyor (deterministik tool)"
                ),
                reason=department_reason.get(name, ""),
            )
        )

    cost_note = (
        "Ücretsiz/yerel katman -- ek maliyet yok."
        if ai_strategy_plan.free_sufficient
        else (
            f"Ücretli katman ({ai_strategy_plan.ai_choice.tier}) -- "
            f"tahmini {ai_strategy_plan.ai_choice.estimated_cost}/1K token."
        )
    )

    return ExecutionPlan(
        steps=tuple(steps),
        risk_level=risk_level,
        estimated_cost=ai_strategy_plan.ai_choice.estimated_cost,
        cost_note=cost_note,
    )


# --- SELF CHECK (Sprint 36) -------------------------------------------------------


@dataclass(frozen=True)
class SelfCheckReport:
    """Sprint 36 SELF CHECK: görev sonunda -- başarı oranı, eksik bilgi,
    tekrar araştırılması gereken yer, (Sprint 34/35'in ZATEN ürettiği)
    daha ucuz/hızlı/yeni-ücretsiz-model değerlendirmesi."""

    success_rate: float
    missing_info: tuple[str, ...]
    needs_reresearch: tuple[str, ...]
    was_cached_research: bool
    cache_note: str
    review: Optional[SelfImprovementReview]
    expected_outputs: tuple[str, ...] = ()
    artifact_statuses: tuple[str, ...] = ()
    remaining: tuple[str, ...] = ()


def task_output_is_false_success(task) -> bool:
    """Sprint 43 (FALSE SUCCESS RECOVERY): bir görev ``TaskStatus.COMPLETED``
    görünmesine rağmen GERÇEK bir çıktı ÜRETMEDİYSE ``True`` döner.

    Bu, aşağıdaki ``build_self_check``'in Sprint 42'den beri ZATEN
    hesapladığı kontrolün (``is_llm_failure``) TEK doğruluk kaynağı olacak
    şekilde buraya çıkarılmış hâlidir -- ikinci bir tespit mantığı İCAT
    EDİLMEDİ. ``src.mission.recovery`` da AYNI bu fonksiyonu kullanır,
    böylece "self-check neyi başarısız sayıyorsa, recovery de TAM ONU
    dener" garantisi tek bir yerden gelir.

    Sprint 43 EKİ: ``is_llm_failure`` yalnızca birkaç Ollama'ya özgü metni
    tanır (bkz. ``src.utils.llm_utils.FAILURE_MARKERS`` -- Sprint 25'in
    kasıtlı dar kapsamı). Kota/rate-limit/auth gibi Sprint 42'nin ZATEN
    kurduğu daha geniş ``FailureClass`` sözlüğüyle eşleşen ama
    ``is_llm_failure``'ın TANIMADIĞI metinler (ör. "429 quota exceeded")
    de aynı şekilde sahte-başarı sayılır -- yeni bir sözlük İCAT EDİLMEDİ,
    ZATEN VAR OLAN ``classify_failure`` (Sprint 42) ikinci bir sinyal
    olarak eklendi. Dairesel import riski yüzünden (``src.mission``
    paketi ``__init__.py``'si ``department_orchestrator`` üzerinden bu
    dosyaya geri dönebilir) import fonksiyon-yerel tutuldu -- bu dosyanın
    zaten kullandığı ``tools_for_department`` deseniyle AYNI."""

    if task.status.value != "completed":
        return False
    if task.result is None:
        return False

    output_text = str(task.result.output)

    if is_llm_failure(output_text):
        return True

    from src.mission.failure_classification import FailureClass, classify_failure

    return classify_failure(output_text) is not FailureClass.UNKNOWN


def build_self_check(mission, review: Optional[SelfImprovementReview]) -> SelfCheckReport:
    """Mission TAMAMLANDIKTAN SONRA (``mission.tasks`` gerçek sonuçlarla
    dolu) çağrılır. Yeni bir ölçüm İCAT ETMEZ -- yalnızca ZATEN
    hesaplanmış sinyalleri (task durumları, Evaluation/Sandbox raporları,
    Sprint 35'in ``SelfImprovementReview``'i) okur/toplar."""

    tasks = mission.tasks
    total = len(tasks)

    missing_info: list[str] = []
    needs_reresearch: list[str] = []
    was_cached_research = False
    cache_note = "Research bu mission'da çalışmadı (veri yok)."
    genuinely_completed = 0

    for task in tasks:
        report = task.metadata.get("report") if task.metadata else None

        if task.handler is None:
            missing_info.append(f"{task.agent}: bağlı değil (henüz gerçek bir modül yok)")
            continue
        if task.status.value != "completed":
            missing_info.append(f"{task.agent}: tamamlanmadı (durum: {task.status.value})")
            continue

        # Sprint 42 SELF CHECK düzeltmesi: "tamamlandı" durumu TEK BAŞINA
        # başarı SAYILMAZ -- görev Sprint 41'in Ollama timeout düzeltmesinden
        # sonra "tamamlanmış" (JobManager düzeyinde temiz) ama İÇERİK bir
        # hata metni ("Ollama zaman aşımına uğradı." vb.) OLABİLİR. Yeni bir
        # hata algılama mantığı İCAT EDİLMEZ -- Research/Finance/Media'nın
        # ZATEN kullandığı ``is_llm_failure`` yeniden kullanılır. Yalnızca
        # GERÇEK bir çıktı üreten görevler ``success_rate``'e sayılır.
        output_text = str(task.result.output) if task.result else ""
        # ``task.result is None`` gerçek çalışmada OLMAZ (``JobManager.
        # run_task`` her terminal durumda ``apply_result`` çağırır) --
        # yalnızca doğrudan ``task.status`` atayan eski/basit test
        # fixture'larında görülür. Bu durumda ceza VERİLMEZ (kanıt YOK,
        # "başarısız" da denemez) -- yalnızca GERÇEK bir sonuç VARSA ve
        # o sonucun metni bir hata işaretiyse başarısız sayılır. Sprint 43:
        # bu kontrol artık ``task_output_is_false_success`` (yukarıda) --
        # ``src.mission.recovery``'nin de kullandığı TEK doğruluk kaynağı.
        if task_output_is_false_success(task):
            missing_info.append(
                f"{task.agent}: tamamlandı ama gerçek içerik üretilemedi (hata: {output_text[:120]})"
            )
            if task.agent != "research":
                continue
            # research'ün önbellek tespiti aşağıda AYRICA çalışsın diye
            # ``continue`` YAPILMAZ -- ama başarı sayılmadı (yukarıda
            # zaten işaretlendi).

        else:
            genuinely_completed += 1

        if task.agent == "research":
            # Not 1: ResearchAgent, github/evaluation/sandbox/integration'ın
            # aksine ``task.metadata["report"]`` YAZMAZ (yalnızca metin
            # döner) -- bu yüzden bu dal ``report`` şartından ÖNCE ve
            # BAĞIMSIZ ele alınır (Sprint 36 canlı testinde yakalanan
            # gerçek bir hata: ``report`` boş olduğu için bu dal hiç
            # ÇALIŞMIYORDU, Research gerçekten çalışmış olsa bile).
            # Not 2: ``task.result.output``, ``BaseAgent.run()``'ın
            # (bkz. src/agents/base_agent.py) sardığı bir ``AgentResult``
            # nesnesidir, DÜZ STRING DEĞİL -- ``report_builder.
            # _other_departments_section``'ın ZATEN yaptığı gibi ``str()``
            # ile metne çevrilir (``AgentResult.__str__`` başarılıysa
            # ``output``'u, değilse ``error``'u döner). Bu da Sprint 36
            # canlı testinde yakalanan GERÇEK bir hataydı (``in`` operatörü
            # ``AgentResult`` üzerinde ÇÖKÜYORDU). Sprint 42: ``output``
            # burada yeniden hesaplanmıyor -- yukarıda zaten hesaplanmış
            # ``output_text`` yeniden kullanılıyor.
            if "daha önce araştırılmış" in output_text:
                was_cached_research = True
                cache_note = "Research önbellekten geldi (KnowledgeBase) -- aynı konu tekrar aranmadı."
            elif output_text:
                was_cached_research = False
                cache_note = "Research yeni bir arama yaptı (önbellekte yoktu)."
            continue

        if not report:
            continue

        if task.agent == "evaluation":
            for candidate in report.get("candidates") or []:
                if candidate.get("sandbox_verdict") == "FAIL":
                    repo = candidate.get("repo")
                    repo_name = repo.full_name if repo is not None else "?"
                    needs_reresearch.append(f"{repo_name}: Sandbox FAIL -- farklı bir aday araştırılmalı.")

        if task.agent == "sandbox":
            result = report.get("result")
            repo = report.get("repo")
            if result is not None and result.status.value != "ready_for_review" and repo is not None:
                needs_reresearch.append(f"{repo.full_name}: Sandbox durumu 'ready_for_review' değil.")

    success_rate = round(100.0 * genuinely_completed / total, 1) if total else 0.0

    # Department completion and user-goal completion are intentionally
    # separate. A successful planning/checklist task cannot satisfy a
    # concrete filesystem artifact or required evaluation evidence.
    from src.mission.completion import evaluate_goal_completion

    goal_completion = evaluate_goal_completion(mission)
    missing_requirements = goal_completion.missing
    if missing_requirements:
        # Keep the task-based metric meaningful while making false 100%
        # impossible. Each unmet goal requirement counts as one incomplete
        # completion unit.
        success_rate = round(
            100.0 * genuinely_completed / (total + len(missing_requirements)), 1
        ) if total else 0.0
        missing_info.extend(
            f"hedef çıktısı eksik: {item.requirement.remaining}"
            for item in missing_requirements
        )

    return SelfCheckReport(
        success_rate=success_rate,
        missing_info=tuple(dict.fromkeys(missing_info)),
        needs_reresearch=tuple(dict.fromkeys(needs_reresearch)),
        was_cached_research=was_cached_research,
        cache_note=cache_note,
        review=review,
        expected_outputs=tuple(item.requirement.name for item in goal_completion.requirements),
        artifact_statuses=tuple(
            "PRESENT" if item.satisfied else "MISSING"
            for item in goal_completion.requirements
        ),
        remaining=tuple(item.requirement.remaining for item in missing_requirements),
    )
