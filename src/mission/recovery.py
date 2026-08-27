from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from src.config.settings import Settings
from src.core.plan_executor import PlanExecutor
from src.core.task_plan import TaskPlan
from src.evolution.collector import EvolutionCollector
from src.evaluation.evaluation_engine import EvaluationEngine
from src.evaluation.relevance import RELEVANCE_LOW_THRESHOLD
from src.github.github_intelligence import GitHubIntelligence
from src.github.models import RepoData
from src.integration.integration_planner import IntegrationPlanner
from src.jobs.job_manager import JobManager
from src.jobs.task import Task
from src.jobs.task_status import TaskStatus
from src.mission.failure_classification import (
    FailureClass,
    classify_failure,
    is_recoverable_via_different_provider,
)
from src.mission.models import Mission
from src.mission.completion import evaluate_goal_completion
from src.providers.provider_manager import ProviderManager
from src.sandbox.models import SandboxStatus
from src.sandbox.sandbox_manager import SandboxManager
from src.security.action_policy import ActionPolicy
from src.strategy.execution_planner import task_output_is_false_success

# Sprint 42: ``CostOptimizer.FREE_TIER_PROVIDERS`` (gemini/groq/openrouter) +
# ollama'nın kendisi -- kullanıcı onayı OLMADAN otomatik olarak denenmesi
# GÜVENLİ sağlayıcı kümesi. "aiml" BİLEREK dışarıda bırakıldı:
# ``CostOptimizer.is_free()`` de onu ücretsiz SAYMAZ (bkz.
# ``src/providers/cost_optimizer.py`` FREE_TIER_PROVIDERS) -- kotalı/gerçek
# faturalandırması olabilecek bir sağlayıcıya SESSİZCE geçmek, bu sprintin
# "asla otonom ücretli çağrı yapma" kuralını ihlal eder. İkinci bir
# ücretsizlik tablosu İCAT EDİLMEDİ -- bu küme kasıtlı olarak
# ``CostOptimizer.FREE_TIER_PROVIDERS`` ile TUTARLI tutuldu.
AUTO_SAFE_PROVIDERS = frozenset({
    "ollama", "gemini", "groq", "openrouter", "codex", "claude_code",
})

# Yalnızca bu departmanların handler'ları provider seçimini gerçekten
# okur. Browser/GitHub gibi tool-first görevleri provider değiştirerek
# tekrar çalıştırmak aynı ağ timeout'unu gereksiz yere yineliyordu.
PROVIDER_BACKED_DEPARTMENTS = frozenset({"research", "finance", "media", "coding"})

# Mission repair (real Swiss-Insider-Shorts failure, ROOT CAUSE B): "media"
# is NOT a single text-LLM-backed capability the way research/finance/coding
# are -- ``MediaManager.plan()`` makes exactly ONE text-LLM call (the
# SENARYO/SAHNELER script/planning prompt), then hands off to entirely
# separate, capability-scoped media providers (NVIDIA/fal/LTX, selected via
# ``src.media.provider_selection.rank_available_providers`` -- see
# ``src.providers.media_provider_base`` for why those are deliberately NOT
# registered in ``ProviderManager``). Swapping ``preferred_ai_provider``
# among AUTO_SAFE_PROVIDERS only ever changes which TEXT provider runs the
# planning call -- it has NO effect on text_to_image/image_to_video/TTS/
# render. ``task.metadata["last_stage"]`` (written live by MediaAgent/
# MediaManager/GeneralProductionBuilder as they progress, see
# ``report_builder._task_note``) is the evidence used to tell these apart.
_MEDIA_TEXT_RECOVERABLE_STAGES = frozenset({"starting", "planning"})


def _media_failure_is_text_recoverable(task: Task) -> bool:
    """``True`` only when the recorded failure point is the text/script
    planning call (or no stage evidence was ever recorded, e.g. a legacy
    task/test predating this tracking -- fails open to the prior behavior
    rather than silently blocking recovery for a genuinely text-only
    failure). ``False`` for any recorded non-text stage (text_to_image/
    image_to_video/audio_narration/render/quality_check/package/...) --
    those need a genuine media-capability route, not a text-provider swap."""

    last_stage = str((task.metadata or {}).get("last_stage") or "")
    if not last_stage:
        return True
    return last_stage in _MEDIA_TEXT_RECOVERABLE_STAGES


# Mission repair (real Swiss-Insider-Shorts follow-up evidence): parses the
# provider/model identity out of a fine-grained stage marker such as
# "text_to_image_scene_1_via_nvidia/sdxl-turbo" (see
# ``src.media.production.GeneralProductionBuilder._generate_scene_image``/
# ``_maybe_generate_scene_motion``). Returns ``None`` for a coarser/older
# marker (e.g. plain "text_to_image_scene_1_of_4", "render", "planning") --
# the capability-specific cooldown/retry below is a no-op without a
# specific provider to cool down.
_MEDIA_STAGE_PROVIDER_PATTERN = re.compile(
    r"^(?P<capability>text_to_image|image_to_video)_scene_\d+(?:_of_\d+)?_via_"
    r"(?P<provider>[^/]+)/(?P<model>.+)$"
)
_MEDIA_CAPABILITY_RETRY_MARKER = "__media_capability_cooldown_retry__"


def _parse_media_stage_provider(last_stage: str) -> tuple[str, str] | None:
    match = _MEDIA_STAGE_PROVIDER_PATTERN.match(last_stage)
    if not match:
        return None
    return match.group("capability"), match.group("provider")


def _cooldown_stalled_media_provider(task: Task) -> None:
    """An outer ``JobManager`` timeout abandons the background thread
    BEFORE ``ProviderExecutionHistory.record()`` ever runs for the stalled
    provider call -- so ``src.media.provider_selection.provider_health``'s
    EXISTING, already-persistent cooldown mechanism never learns this
    provider just failed, and would rank the SAME provider first again on
    a bare retry. This records the missing failure entry directly into
    that SAME store (no second tracking system) so the next
    ``rank_available_providers`` call naturally deprioritizes it."""

    last_stage = str((task.metadata or {}).get("last_stage") or "")
    parsed = _parse_media_stage_provider(last_stage)
    if parsed is None:
        return
    capability, provider_id = parsed
    from src.providers.execution_history import ProviderExecutionHistory
    ProviderExecutionHistory().record(
        task_type=capability, provider=provider_id, success=False, fallback_used=False,
        duration_seconds=float(task.timeout_seconds or 0.0),
    )


class RecoveryStep(str, Enum):
    """Sprint 42 KURTARMA MERDİVENİ -- spesifikasyondaki 11 basamak, aynı
    sırayla. Bu kodda GERÇEKTEN uygulanabilen basamaklar (1, 2/3, 6, 11)
    somut eylemler üretir; diğerleri (4/5/7/8/9/10) bu mimaride şu an
    karşılığı olmadığı için raporlarda dürüstçe "uygulanamaz" notuyla
    geçilir -- var olmayan bir yetenek TAKLİT EDİLMEZ."""

    # Mission repair (ROOT CAUSE B -- provider vs. capability fallback):
    # recorded INSTEAD OF the provider ladder when a media task failed on a
    # non-text capability (text_to_image/image_to_video/render/audio/...) --
    # swapping the TEXT ``preferred_ai_provider`` (ollama/gemini/claude_code/
    # codex) cannot fix that, so the ladder is skipped, evidenced, not
    # silently dropped.
    NON_TEXT_MEDIA_CAPABILITY_GAP = "0_non_text_media_capability_gap"
    SAME_METHOD_RETRY = "1_same_method_retry"
    ANOTHER_LOCAL_MODEL = "2_another_local_model"
    ANOTHER_FREE_PROVIDER = "3_another_free_provider"
    GOAL_SPECIFIC_FREE_DISCOVERY = "6_goal_specific_free_discovery"
    PAID_APPROVAL_REQUIRED = "11_paid_approval_required"


@dataclass
class RecoveryAttempt:
    task_id: str
    department: str
    failure_class: FailureClass
    step: RecoveryStep
    provider_tried: str | None
    succeeded: bool
    note: str


@dataclass
class RecoveryAttemptHistory:
    """Tek bir mission'ın kurtarma denemeleri boyunca AYNI (görev + yöntem)
    kombinasyonunu tekrar TEKRAR denememesi için (Sprint 42 ANTI-INFINITE-
    LOOP kuralı). Yeni bir kalıcı durum/veritabanı İCAT ETMEZ -- mission
    çalışırken bellek içinde tutulan basit bir liste (``ProviderExecutionHistory``
    ile KARIŞTIRILMAMALI; o kalıcı/diskte, bu geçici/tek-mission ömürlü)."""

    attempts: list[RecoveryAttempt] = field(default_factory=list)
    attempted_providers: dict[str, set[str]] = field(default_factory=dict)

    def already_tried(self, task_id: str, method: str) -> bool:
        return any(a.task_id == task_id and a.provider_tried == method for a in self.attempts)

    def record(self, attempt: RecoveryAttempt) -> None:
        self.attempts.append(attempt)

    def tried_methods_for(self, task_id: str) -> set[str]:
        recorded = {a.provider_tried for a in self.attempts if a.task_id == task_id and a.provider_tried}
        return recorded | self.attempted_providers.get(task_id, set())

    def mark_provider_tried(self, task_id: str, provider: str) -> None:
        if provider:
            self.attempted_providers.setdefault(task_id, set()).add(provider)


@dataclass
class DiscoveryOutcome:
    department: str
    focus: str
    ran: bool
    reason: str
    candidates: list[dict] = field(default_factory=list)


@dataclass
class MissionRecoveryReport:
    goal: str
    ran: bool = False
    attempts: list[RecoveryAttempt] = field(default_factory=list)
    resolved_task_ids: list[str] = field(default_factory=list)
    resumed_task_ids: list[str] = field(default_factory=list)
    still_failed_task_ids: list[str] = field(default_factory=list)
    approval_required: list[dict] = field(default_factory=list)
    discovery_runs: list[DiscoveryOutcome] = field(default_factory=list)
    evaluated_candidates: list[dict] = field(default_factory=list)
    sandboxed_candidates: list[dict] = field(default_factory=list)
    integrated_candidates: list[dict] = field(default_factory=list)
    used_candidates: list[dict] = field(default_factory=list)
    remaining_goals: list[str] = field(default_factory=list)
    blocked: bool = False


# Görev türüne göre "hedefe özgü" keşif odak sorgusu -- yeni bir keşif
# motoru İCAT EDİLMEDİ (bkz. ``src.evolution.EvolutionCollector``),
# yalnızca ODAK sorgusu mission'ın GERÇEK hedefine bağlandı. Tanımlı
# olmayan bir mission türü için keşif hiç TETİKLENMEZ (dürüst "uygulanamaz").
_DISCOVERY_FOCUS_BY_MISSION_TYPE: dict[str, str] = {
    "youtube": "free open source AI video generation text-to-speech thumbnail tools",
    "media": "free open source AI video generation text-to-speech thumbnail tools",
    "finance": "free market data news API financial analysis backtesting tools",
    "code": "free open source AI coding assistant static analysis tools",
    "social_media": "free social media automation posting API tools",
    "security": "free open source security scanning vulnerability tools",
    "learning": "free open source educational content generation tools",
    "automation": "free open source workflow automation tools",
}


def _failure_text(task: Task) -> str:
    if task.result is not None and task.result.output:
        return str(task.result.output)
    return task.error or ""


def _department_fallback_provider(mission: Mission, department: str) -> str | None:
    """Sprint 34/40'ta departman başına ZATEN hesaplanmış (ama bu sprinte
    kadar hiçbir yerde OKUNMAMIŞ) ``AIChoice.fallback_provider``'ı okur --
    yeni bir fallback hesaplaması İCAT ETMEZ."""

    if mission.ai_strategy is None:
        return None
    choice = mission.ai_strategy.department_ai_choices.get(department)
    if choice is None:
        return None
    return choice.fallback_provider


def _candidate_providers(
    provider_manager: ProviderManager,
    mission: Mission,
    task: Task,
    already_tried: set[str],
) -> list[str]:
    """Sırasıyla: departmanın ZATEN hesaplanmış ``fallback_provider``'ı,
    sonra kullanılabilir diğer tüm GÜVENLİ (ücretsiz) sağlayıcılar. Zaten
    denenmiş, şu an kullanılamayan veya ücretsiz OLMAYAN hiçbir şey
    önerilmez -- kullanıcı onayı olmadan asla ücretliye geçilmez."""

    ordered: list[str] = []

    # İki coding worker kör round-robin değildir; biri limit/unavailable
    # olduğunda önce diğer mevcut abonelik worker'ı denenir, sonra local/free
    # merdiven aynen devam eder.
    current = ProviderManager.normalize(str(task.metadata.get("preferred_ai_provider") or ""))
    worker_counterpart = {"codex": "claude_code", "claude_code": "codex"}.get(current)
    if worker_counterpart:
        ordered.append(worker_counterpart)

    fallback = _department_fallback_provider(mission, task.agent)
    if fallback:
        ordered.append(ProviderManager.normalize(fallback))

    for name in provider_manager.available_names():
        normalized = ProviderManager.normalize(name)
        if normalized not in ordered:
            ordered.append(normalized)

    result: list[str] = []
    for name in ordered:
        if name in already_tried or name == current or name in result:
            continue
        if name not in AUTO_SAFE_PROVIDERS:
            continue
        provider = provider_manager.get(name)
        if provider is None or not provider.is_available():
            continue
        result.append(name)
    return result


def _remaining_paid_providers(provider_manager: ProviderManager, tried_all: set[str]) -> list[str]:
    """Henüz DENENMEMİŞ, kullanılabilir ama ücretsiz/güvenli OLMAYAN
    sağlayıcıların listesini döndürür -- yalnızca bunlar varsa "kullanıcı
    onayı gerekiyor" mesajı doğru şekilde "ücretli sağlayıcı kaldı" der;
    hiç yoksa (hiçbir seçenek kalmadıysa) dürüstçe farklı bir not yazılır."""

    result: list[str] = []
    for name in provider_manager.available_names():
        normalized = ProviderManager.normalize(name)
        if normalized not in AUTO_SAFE_PROVIDERS and normalized not in tried_all and normalized not in result:
            result.append(normalized)
    return result


_SAME_METHOD_MARKER = "__same_method_retry__"
_LADDER_EXHAUSTED_MARKER = "__ladder_exhausted__"


def _task_genuinely_succeeded(task: Task) -> bool:
    """Sprint 43 (FALSE SUCCESS RECOVERY): ``task.status == COMPLETED``
    TEK BAŞINA yeterli DEĞİLDİR -- görev "tamamlandı" görünüp GERÇEK bir
    çıktı üretmemiş olabilir (ör. "Ollama zaman aşımına uğradı." metni
    ile COMPLETED). Bu, ``build_self_check``'in ZATEN kullandığı AYNI
    ``task_output_is_false_success`` ile (TEK doğruluk kaynağı) kontrol
    edilir -- ikinci bir tespit mantığı İCAT EDİLMEDİ."""

    return task.status == TaskStatus.COMPLETED and not task_output_is_false_success(task)


def _needs_recovery(task: Task) -> bool:
    """Bir görev kurtarma sürecine (``recover_mission``) girmeli mi?
    İki durum: (1) klasik ``TaskStatus.FAILED`` (Sprint 42), (2) YENİ
    (Sprint 43) -- ``COMPLETED`` görünüp ``task_output_is_false_success``
    olan "sahte başarı"."""

    from src.mission.task_criticality import is_supporting_task
    if is_supporting_task(task):
        return False
    if task.status == TaskStatus.FAILED:
        return True
    return task_output_is_false_success(task)


def plan_needs_recovery(plan: TaskPlan, mission: Mission | None = None) -> bool:
    """Sprint 43: ``CEO.dispatch_mission``'ın kurtarmayı TETİKLEME kararı
    için kullandığı tek satırlık kapı -- eskiden yalnızca
    ``plan.has_failed()`` (klasik FAILED) kontrol ediliyordu; artık
    ``_needs_recovery`` (FAILED + false-success) ile AYNI, TEK doğruluk
    kaynağını kullanır -- ikinci bir tetikleme mantığı İCAT EDİLMEDİ."""

    if any(_needs_recovery(task) for task in plan.all_tasks()):
        return True
    return bool(mission is not None and evaluate_goal_completion(mission).missing)


def recover_task(
    task: Task,
    mission: Mission,
    *,
    provider_manager: ProviderManager,
    job_manager: JobManager,
    history: RecoveryAttemptHistory,
) -> list[RecoveryAttempt]:
    """Tek bir BAŞARISIZ görevi, kurtarma merdiveninin PROVIDER
    basamaklarını (1, 2/3, 11) izleyerek yeniden dener.

    Görevin handler'ı (ör. ``FinanceManager.plan``/``ResearchAgent.run``)
    DEĞİŞTİRİLMEZ -- yalnızca ``task.metadata["preferred_ai_provider"]``
    değiştirilip AYNI handler, ZATEN VAR OLAN ``JobManager.run_task`` ile
    YENİDEN çağrılır (yeni bir yürütme motoru İCAT EDİLMEDİ).
    """

    attempts: list[RecoveryAttempt] = []

    if task.handler is None:
        # Bu görevin arkasında hiç GERÇEK bir alt sistem yok (capability
        # gap) -- provider değişimi anlamsız, bu ``recover_mission``'da
        # ayrıca ele alınır (bkz. ``discover_for_goal``).
        return attempts

    failure_class = classify_failure(_failure_text(task))
    if task.agent not in PROVIDER_BACKED_DEPARTMENTS:
        return attempts
    current_provider = ProviderManager.normalize(str(task.metadata.get("preferred_ai_provider") or ""))
    history.mark_provider_tried(task.id, current_provider)

    if not is_recoverable_via_different_provider(failure_class):
        return attempts

    def _rerun() -> None:
        original_timeout = task.timeout_seconds
        # Sprint: research/production pipeline audit -- a real Swiss Insider
        # mission run failed with "Task timed out (20.0 sec)": a genuine
        # TIMEOUT failure means the FULL department budget (already sized to
        # real worst-case latency, see DEPARTMENT_TASK_TIMEOUT_SECONDS/
        # CODING_.../RESEARCH_... in department_orchestrator.py) wasn't
        # enough -- retrying with the OLD flat 20s cap (smaller than even
        # ONE inner provider call's own timeout) could only ever guarantee a
        # second, faster failure for genuinely slow-but-correct work (a real
        # multi-source web search, a real local Ollama call). The retry
        # window is now configurable/bounded
        # (Settings.RECOVERY_SAME_METHOD_RETRY_TIMEOUT_SECONDS) but never
        # exceeds the department's OWN outer budget -- same inner-never-
        # exceeds-outer invariant as the coding department, applied to the
        # retry window instead of a subprocess.
        if failure_class == FailureClass.TIMEOUT and original_timeout:
            task.timeout_seconds = min(original_timeout, Settings.RECOVERY_SAME_METHOD_RETRY_TIMEOUT_SECONDS)
        task.status = TaskStatus.PENDING
        task.error = ""
        task.result = None
        try:
            job_manager.run_task(task)
        finally:
            task.timeout_seconds = original_timeout

    if task.agent == "media" and not _media_failure_is_text_recoverable(task):
        last_stage = str((task.metadata or {}).get("last_stage") or "bilinmiyor")
        base_note = (
            f'Metin sağlayıcı (ollama/gemini/claude_code/codex) merdiveni ATLANDI -- '
            f'başarısızlık text-planning DIŞINDA bir aşamada ("{last_stage}") oluştu; '
            "bu aşama ayrı, yeteneğe-özel media provider'lar (bkz. "
            "src.media.provider_selection) gerektirir, genel bir metin sağlayıcı değişimi "
            "onu düzeltemez."
        )

        # Mission repair (real Swiss-Insider-Shorts follow-up evidence): a
        # bounded, CAPABILITY-specific fallback -- reuses the EXISTING
        # ``rank_available_providers``/``provider_health`` cooldown
        # mechanism (never invents a new provider). An outer JobManager
        # timeout abandons the stalled provider call's thread before it can
        # record its own failure, so that mechanism would otherwise stay
        # unaware and rank the SAME stalled provider first again -- fixed
        # by recording the missing failure entry directly, from the
        # provider/model identity now carried in ``last_stage`` (see
        # ``src.media.production._generate_scene_image``).
        if history.already_tried(task.id, _MEDIA_CAPABILITY_RETRY_MARKER):
            attempt = RecoveryAttempt(
                task_id=task.id, department=task.agent, failure_class=failure_class,
                step=RecoveryStep.NON_TEXT_MEDIA_CAPABILITY_GAP, provider_tried=None, succeeded=False,
                note=base_note + " Yeteneğe-özel sınırlı (1 kez) yeniden deneme zaten tüketildi.",
            )
            history.record(attempt)
            attempts.append(attempt)
            return attempts

        _cooldown_stalled_media_provider(task)
        _rerun()
        succeeded = _task_genuinely_succeeded(task)
        attempt = RecoveryAttempt(
            task_id=task.id, department=task.agent, failure_class=failure_class,
            step=RecoveryStep.NON_TEXT_MEDIA_CAPABILITY_GAP, provider_tried=_MEDIA_CAPABILITY_RETRY_MARKER,
            succeeded=succeeded,
            note=base_note + (
                " Sağlayıcı sağlık geçmişine bu zaman aşımı BAŞARISIZLIK olarak kaydedildi (bkz. "
                "ProviderExecutionHistory/provider_health); ZATEN sıralı media provider'lar arasından "
                "SINIRLI (1 kez) bir yeniden deneme yapıldı -- "
                + ("BAŞARILI." if succeeded else "yine başarısız.")
            ),
        )
        history.record(attempt)
        attempts.append(attempt)
        if succeeded or not _media_failure_is_text_recoverable(task):
            # Either fixed, or still failing on a non-text stage -- either
            # way, the generic text-provider ladder below must not run.
            return attempts
        failure_class = classify_failure(_failure_text(task))
        if not is_recoverable_via_different_provider(failure_class):
            return attempts
        # Falls through only if the bounded retry now fails at the TEXT
        # planning stage instead -- a genuinely different, text-recoverable
        # failure, where the normal ladder below is the correct next step.

    # Basamak 1: AYNI yöntemle GÜVENLİ bir kez daha dene. Task Engine'in
    # kendi ``max_retries``'ı GERÇEK mission akışında hiçbir yerde
    # ayarlanmadığı için (bkz. ``Task.max_retries`` varsayılanı 0) fiilen
    # HİÇ çalışmıyor -- bu basamak burada AÇIKÇA uygulanıyor, ikinci bir
    # retry mimarisi İCAT EDİLMEDİ, yalnızca ZATEN VAR OLAN
    # ``JobManager.run_task`` tekrar çağrılıyor.
    # Repeating the same timeout/rate-limited operation only duplicates the
    # full wait.  Provider fallback remains available below where meaningful.
    skip_same_method = failure_class == FailureClass.RATE_LIMIT
    if not skip_same_method and not history.already_tried(task.id, _SAME_METHOD_MARKER):
        current_provider = task.metadata.get("preferred_ai_provider") or "varsayılan"
        _rerun()
        succeeded = _task_genuinely_succeeded(task)
        attempt = RecoveryAttempt(
            task_id=task.id, department=task.agent, failure_class=failure_class,
            step=RecoveryStep.SAME_METHOD_RETRY, provider_tried=_SAME_METHOD_MARKER,
            succeeded=succeeded,
            note=f'Aynı yöntemle ("{current_provider}") güvenli tekrar deneme.',
        )
        history.record(attempt)
        attempts.append(attempt)

        if succeeded:
            return attempts

        failure_class = classify_failure(_failure_text(task))
        if not is_recoverable_via_different_provider(failure_class):
            return attempts

    tried = history.tried_methods_for(task.id)

    # Basamak 2/3: başka bir ücretsiz/yerel sağlayıcı (departmanın ZATEN
    # hesaplanmış ``fallback_provider``'ı ÖNCELİKLİ).
    for provider_name in _candidate_providers(provider_manager, mission, task, tried):
        history.mark_provider_tried(task.id, provider_name)
        task.metadata["preferred_ai_provider"] = provider_name
        _rerun()
        succeeded = _task_genuinely_succeeded(task)
        step = (
            RecoveryStep.ANOTHER_LOCAL_MODEL
            if provider_name == ProviderManager.normalize("ollama")
            else RecoveryStep.ANOTHER_FREE_PROVIDER
        )
        attempt = RecoveryAttempt(
            task_id=task.id, department=task.agent, failure_class=failure_class,
            step=step, provider_tried=provider_name, succeeded=succeeded,
            note=f'Alternatif ücretsiz sağlayıcı denendi: "{provider_name}".',
        )
        history.record(attempt)
        attempts.append(attempt)

        if succeeded:
            return attempts

        failure_class = classify_failure(_failure_text(task))
        if not is_recoverable_via_different_provider(failure_class):
            return attempts

        tried = history.tried_methods_for(task.id)

    # Basamak 11: merdiven tükendi (ne aynı yöntem ne de var olan hiçbir
    # ücretsiz/yerel sağlayıcı işe yaradı) -- OTOMATİK ÇAĞRI YAPILMAZ,
    # yalnızca "kullanıcı onayı gerekiyor" olarak işaretlenir. ANTI-
    # INFINITE-LOOP: bu basamak bir görev için yalnızca BİR KEZ kaydedilir
    # (``_LADDER_EXHAUSTED_MARKER``) -- aynı görev tekrar tekrar
    # ``recover_task``'a verilse bile (ör. üst seviye bir döngü hatası)
    # burada YENİDEN bir handler çağrısı YAPILMAZ.
    if not history.already_tried(task.id, _LADDER_EXHAUSTED_MARKER):
        tried_all = history.tried_methods_for(task.id) | {_SAME_METHOD_MARKER}
        remaining_paid = _remaining_paid_providers(provider_manager, tried_all)

        if remaining_paid:
            note = (
                "Tüm ücretsiz/yerel seçenekler tükendi -- yalnızca ücretli "
                f"sağlayıcı(lar) ({', '.join(sorted(remaining_paid))}) kaldı. "
                "KURAL gereği kullanıcı onayı OLMADAN çağrılmadı."
            )
        else:
            note = "Tüm ücretsiz/yerel/mevcut seçenekler tükendi -- devam etmek için kullanıcı girdisi gerekiyor."

        attempt = RecoveryAttempt(
            task_id=task.id, department=task.agent, failure_class=failure_class,
            step=RecoveryStep.PAID_APPROVAL_REQUIRED, provider_tried=_LADDER_EXHAUSTED_MARKER,
            succeeded=False, note=note,
        )
        history.record(attempt)
        attempts.append(attempt)

    return attempts


def discover_for_goal(
    mission: Mission,
    task: Task,
    evolution_collector: EvolutionCollector | None = None,
) -> DiscoveryOutcome:
    """Sprint 42 GOAL-DRIVEN DISCOVERY: yalnızca mission'ın GERÇEK
    hedefiyle İLGİLİ, DAR bir odakla (bkz.
    ``_DISCOVERY_FOCUS_BY_MISSION_TYPE``) ZATEN VAR OLAN
    ``EvolutionCollector``'ı çağırır -- yeni bir keşif motoru İCAT
    EDİLMEZ. ``broad=False`` ile ``EvolutionCollector``'ın kendi 5 sabit
    genel sorgusu ATLANIR (bkz. ``src/evolution/collector.py``) -- amaç,
    hedefle İLGİSİZ geniş bir AI-dünyası taramasının YAPILMAMASIdır
    (Sprint 42 TEST E/F).
    """

    # A declared capability gap is more precise than a mission-type table and
    # works for every goal type.  Keep the old table as backwards-compatible
    # fallback for handler-less legacy tasks.
    missing_outputs = [
        item.requirement.name for item in evaluate_goal_completion(mission).missing
    ]
    gap_terms = list(mission.capability_gaps) + missing_outputs
    focus = (
        "free local open source " + " ".join(dict.fromkeys(gap_terms))
        + f" capability for {mission.goal or mission.title}"
        if gap_terms
        else _DISCOVERY_FOCUS_BY_MISSION_TYPE.get(mission.mission_type.value)
    )

    if not focus:
        return DiscoveryOutcome(
            department=task.agent, focus="", ran=False,
            reason=f'"{mission.mission_type.value}" için tanımlı bir hedef-odaklı keşif sorgusu yok.',
        )

    collector = evolution_collector or EvolutionCollector()

    try:
        results = collector.collect(focus=focus, broad=False)
    except Exception as error:
        return DiscoveryOutcome(
            department=task.agent, focus=focus, ran=False,
            reason=f"Keşif başarısız oldu: {error}",
        )

    return DiscoveryOutcome(
        department=task.agent, focus=focus, ran=True,
        reason=f'"{task.agent}" departmanı için hedefe özgü ücretsiz kaynak keşfi çalıştırıldı.',
        candidates=results,
    )


def _candidate_key(candidate: dict) -> str:
    return str(candidate.get("url") or candidate.get("repository_url") or candidate.get("title") or "").strip()


def _remember_candidates(mission: Mission, candidates: list[dict]) -> None:
    """Merge candidates without discarding evidence gathered earlier."""
    known = {_candidate_key(item) for item in mission.capability_candidates}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        key = _candidate_key(candidate)
        if key and key not in known:
            mission.capability_candidates.append(dict(candidate))
            known.add(key)


def _existing_mission_candidates(mission: Mission, plan: TaskPlan) -> list[dict]:
    """Collect candidate rows already produced by GitHub/discovery tasks."""
    found: list[dict] = list(mission.capability_candidates)
    for task in plan.all_tasks():
        report = task.metadata.get("report")
        if not isinstance(report, dict):
            continue
        rows = report.get("candidates") or report.get("top") or report.get("recommendations") or []
        if isinstance(rows, list):
            found.extend(row for row in rows if isinstance(row, dict))
        repo = report.get("repo")
        if isinstance(repo, RepoData):
            found.append({"title": repo.full_name, "url": repo.url, "repo": repo, "source_task_id": task.id})
    return found


# Mission repair (real Swiss-Insider-Shorts failure, ROOT CAUSE C): the
# candidate list used to shrink silently (3 found -> 1 evaluated -> 0
# sandboxed -> 0 integrated) with no record of WHY a candidate dropped out
# at each stage. Every candidate now keeps an explicit terminal
# ``candidate["status"]``/``candidate["status_reason"]`` -- nothing is
# removed from ``mission.capability_candidates``, only annotated in place,
# so the mission report can explain every candidate instead of just
# printing shrinking list lengths (see ``report_builder``).
CANDIDATE_DISCOVERED = "DISCOVERED"
CANDIDATE_UNRESOLVED = "UNRESOLVED_NOT_A_REPOSITORY"
CANDIDATE_REJECTED_RELEVANCE = "REJECTED_RELEVANCE"
CANDIDATE_EVALUATION_FAILED = "EVALUATION_FAILED"
CANDIDATE_SANDBOX_FAILED = "SANDBOX_FAILED"
CANDIDATE_INTEGRATION_APPROVAL_REQUIRED = "INTEGRATION_APPROVAL_REQUIRED"
CANDIDATE_DISCOVERY_ERROR = "DISCOVERY_ERROR"


def _repo_for_candidate(candidate: dict, github: GitHubIntelligence) -> RepoData | None:
    repo = candidate.get("repo")
    if isinstance(repo, RepoData):
        return repo
    url = str(candidate.get("url") or candidate.get("repository_url") or "")
    marker = "github.com/"
    if marker not in url.lower():
        return None
    full_name = url.split(marker, 1)[1].strip("/").split("/")
    if len(full_name) < 2:
        return None
    try:
        return github.get_repository("/".join(full_name[:2]))
    except Exception:
        return None


def _continue_capability_gaps(
    mission: Mission,
    plan: TaskPlan,
    report: MissionRecoveryReport,
    *,
    evolution_collector: EvolutionCollector | None,
    job_manager: JobManager,
) -> None:
    """Connect gap -> discovery -> validation -> safe existing use.

    Acquisition that installs/edits production code remains behind the
    existing ActionPolicy. Static sandbox analysis is the automatic safe
    acquisition boundary.
    """
    if not mission.capability_gaps:
        return

    _remember_candidates(mission, _existing_mission_candidates(mission, plan))
    probe = Task(title="capability discovery", agent="capability", handler=None)
    outcome = discover_for_goal(mission, probe, evolution_collector)
    report.discovery_runs.append(outcome)
    _remember_candidates(mission, outcome.candidates)

    evaluator = EvaluationEngine()
    github = GitHubIntelligence()
    sandbox = SandboxManager()
    integrator = IntegrationPlanner()
    policy = ActionPolicy()

    for candidate in mission.capability_candidates:
        candidate.setdefault("status", CANDIDATE_DISCOVERED)
        try:
            repo = _repo_for_candidate(candidate, github)
            if repo is None:
                candidate["status"] = CANDIDATE_UNRESOLVED
                candidate["status_reason"] = (
                    "Aday bir GitHub repo URL'sine çözümlenemedi (uzak API/sağlayıcı adayı "
                    "olabilir -- bu döngü yalnızca GitHub repo edinme yolunu değerlendirir)."
                )
                continue
            evaluation = evaluator.evaluate(repo)
            candidate["evaluation"] = evaluation
            report.evaluated_candidates.append({"url": repo.url, "suitable": evaluation.suitable_for_jarvis})
            if not evaluation.suitable_for_jarvis or evaluation.risk_level == "HIGH":
                if evaluation.relevance_score < RELEVANCE_LOW_THRESHOLD:
                    candidate["status"] = CANDIDATE_REJECTED_RELEVANCE
                else:
                    candidate["status"] = CANDIDATE_EVALUATION_FAILED
                candidate["status_reason"] = evaluation.recommendation
                continue
            sandbox_result = sandbox.run_pipeline(repo.url, evaluation, repo=repo)
            candidate["sandbox_status"] = sandbox_result.status.value
            report.sandboxed_candidates.append({"url": repo.url, "status": sandbox_result.status.value})
            try:
                if sandbox_result.status != SandboxStatus.READY_FOR_REVIEW:
                    candidate["status"] = CANDIDATE_SANDBOX_FAILED
                    candidate["status_reason"] = (
                        "; ".join(sandbox_result.findings) if sandbox_result.findings
                        else sandbox_result.recommended_action or sandbox_result.status.value
                    )
                    continue
                integration_plan = integrator.analyze(sandbox_result, evaluation)
                candidate["integration"] = integration_plan
                candidate["status"] = CANDIDATE_INTEGRATION_APPROVAL_REQUIRED
                candidate["status_reason"] = (
                    "Sandbox PASS + Integration planı hazır; kod kurulumu/entegrasyonu ActionPolicy "
                    "onayı olmadan OTOMATİK yapılmaz (bkz. mevcut approval kapısı)."
                )
                report.integrated_candidates.append({"url": repo.url, "merge_ready": integration_plan.merge_ready})
            finally:
                sandbox.cleanup(sandbox_result)
        except Exception as error:
            # One bad candidate must not discard the rest of the mission's
            # candidate pool or skip the original-goal resume attempt.
            candidate["status"] = CANDIDATE_DISCOVERY_ERROR
            candidate["status_reason"] = str(error)
            candidate["continuation_error"] = str(error)
            continue

    # A mission-local producer may advertise the missing capability. This is
    # the only automatic use route: it already has a registered handler and
    # its action must pass the existing approval policy.
    for gap in mission.capability_gaps:
        producer = next((
            task for task in plan.all_tasks()
            if gap in tuple(task.metadata.get("provides_capabilities") or ())
            and task.handler is not None
        ), None)
        if producer is None:
            continue
        action = str(producer.metadata.get("safe_use_action") or "")
        decision = policy.evaluate(action)
        if not decision.allowed or decision.requires_confirmation:
            report.approval_required.append({
                "task_id": producer.id, "department": producer.agent,
                "need": gap, "why": decision.reason,
                "why_free_insufficient": "Mevcut adayın kullanımı approval policy kapısında durdu.",
            })
            continue
        producer.status = TaskStatus.PENDING
        producer.error = ""
        producer.result = None
        job_manager.run_task(producer)
        if _task_genuinely_succeeded(producer):
            report.used_candidates.append({"task_id": producer.id, "capability": gap, "action": action})
            report.resumed_task_ids.extend(_reset_stale_dependents(plan, producer))
            mission.current_capabilities = tuple(dict.fromkeys((*mission.current_capabilities, gap)))
            mission.capability_gaps = tuple(item for item in mission.capability_gaps if item != gap)
            mission.discovery_required = bool(mission.capability_gaps)


def _reset_stale_dependents(plan: TaskPlan, task: Task) -> list[str]:
    """``task`` artık GERÇEKTEN başarılı olduğu için, ona (doğrudan/dolaylı)
    bağımlı, hâlâ GEÇERSİZ kalmış görevleri PENDING'e döndürür.

    İki durum: (1) daha önce CANCELLED kalmışlar (klasik ``TaskStatus.
    FAILED`` sonrası, Sprint 42) -- bunlar hiç ÇALIŞMAMIŞTI. (2) Sprint 43
    (FALSE SUCCESS): ``task`` bir "sahte başarı" idiyse, ona bağımlı
    görevler ``is_ready()``'nin ``status == COMPLETED`` şartını YANLIŞLIKLA
    zaten karşılamış ve ONUN BOZUK çıktısıyla ÇALIŞMIŞ olabilir -- bu
    yüzden COMPLETED bağımlılar da (yalnızca ``task``'in bağımlıları,
    ilgisiz dallar DEĞİL) TAZE bir çalıştırma için sıfırlanır. Zaten VAR
    OLAN ``TaskPlan``/``TaskQueue`` yapısı yeniden kullanılır -- ikinci bir
    checkpoint mekanizması İCAT EDİLMEZ; ``PlanExecutor.run()`` bu
    görevleri normal ``next_ready()`` akışıyla YENİDEN ele alacaktır."""

    reset_ids: list[str] = []
    for other in plan.all_tasks():
        if other.status in (TaskStatus.CANCELLED, TaskStatus.COMPLETED) and task.id in other.depends_on:
            other.status = TaskStatus.PENDING
            other.error = ""
            other.result = None
            reset_ids.append(other.id)
            reset_ids.extend(_reset_stale_dependents(plan, other))
    return reset_ids


def recover_mission(
    mission: Mission,
    plan: TaskPlan,
    *,
    provider_manager: ProviderManager | None = None,
    evolution_collector: EvolutionCollector | None = None,
    history: RecoveryAttemptHistory | None = None,
) -> MissionRecoveryReport:
    """Sprint 42/43 ana giriş noktası: bir Mission dispatch edildikten
    sonra GERÇEKTEN başarısız kalan görevleri "provider'ı değil hedefi
    koru" ilkesiyle kurtarmaya çalışır.

    "Gerçekten başarısız" iki şeyi kapsar (bkz. ``_needs_recovery``): (1)
    klasik ``TaskStatus.FAILED`` (Sprint 42), (2) Sprint 43 FALSE SUCCESS
    -- ``COMPLETED`` görünüp ``task_output_is_false_success`` olan görevler
    (``build_self_check``'in Sprint 42'den beri ZATEN tespit ettiği AYNI
    durum -- burada yalnızca aynı tespite BAĞLANDI, ikinci bir tespit
    mantığı İCAT EDİLMEDİ).

    Genuinely başarılı hiçbir görev DOKUNULMAZ/yeniden ÇALIŞTIRILMAZ
    (checkpoint/resume) -- yalnızca bu iki sınıftan biri ve onların
    (kurtarma başarılı olursa) hâlâ GEÇERSİZ kalmış bağımlıları yeniden
    ele alınır. Yeni bir Mission/Task/Plan sistemi İCAT EDİLMEZ -- AYNI
    ``plan`` nesnesi üzerinde çalışılır.
    """

    provider_manager = provider_manager or ProviderManager()
    history = history or RecoveryAttemptHistory()
    job_manager = JobManager()

    failed_tasks = [t for t in plan.all_tasks() if _needs_recovery(t)]
    missing_goal_requirements = list(evaluate_goal_completion(mission).missing)
    report = MissionRecoveryReport(
        goal=mission.goal or mission.title,
        ran=bool(failed_tasks or missing_goal_requirements),
    )

    if not failed_tasks and not missing_goal_requirements:
        return report

    any_fixed = False

    # Goal-level gaps are independent of task failure. They must enter the
    # continuation chain before artifact recovery can declare exhaustion.
    _continue_capability_gaps(
        mission, plan, report,
        evolution_collector=evolution_collector, job_manager=job_manager,
    )

    for task in failed_tasks:
        task_attempts = recover_task(
            task, mission,
            provider_manager=provider_manager, job_manager=job_manager, history=history,
        )
        report.attempts.extend(task_attempts)

        if _task_genuinely_succeeded(task):
            report.resolved_task_ids.append(task.id)
            report.resumed_task_ids.extend(_reset_stale_dependents(plan, task))
            any_fixed = True
            continue

        report.still_failed_task_ids.append(task.id)

        for attempt in task_attempts:
            if attempt.step == RecoveryStep.PAID_APPROVAL_REQUIRED:
                report.approval_required.append({
                    "task_id": task.id,
                    "department": task.agent,
                    "need": f'"{task.agent}" görevi için ücretli bir sağlayıcı gerekiyor.',
                    "why": _failure_text(task) or "bilinmeyen hata",
                    "why_free_insufficient": "Tüm ücretsiz/yerel seçenekler denendi ve tükendi.",
                })

        # GOAL-DRIVEN DISCOVERY: yalnızca bu görevin ARKASINDA GERÇEK bir
        # alt sistem/handler hiç YOKSA (capability gap) tetiklenir --
        # ZATEN VAR OLAN bir yetenek provider hatasıyla başarısız olduysa
        # (yukarıdaki provider basamakları zaten denendiyse) hiç
        # TETİKLENMEZ (TEST F: gereksiz keşif yapılmaz).
        if task.handler is None and not mission.capability_gaps:
            report.discovery_runs.append(discover_for_goal(mission, task, evolution_collector))

    if any_fixed:
        PlanExecutor(job_manager, cancel_on_failure=False).run(plan)

    # Artifact/evidence recovery is goal-level: completed research/github/
    # browser checkpoints stay untouched. A producer may explicitly declare
    # that its existing handler is a safe local/free artifact recovery route;
    # only that producer is retried. Coding workers are never selected here.
    for missing in list(evaluate_goal_completion(mission).missing):
        requirement = missing.requirement
        producer = next((
            task for task in plan.all_tasks()
            if task.agent in {"media", "automation"}
            and task.metadata.get("artifact_recovery_available") is True
            and task.handler is not None
        ), None)
        if requirement.kind == "artifact" and producer is not None:
            producer.status = TaskStatus.PENDING
            producer.error = ""
            producer.result = None
            job_manager.run_task(producer)
        elif requirement.kind == "finance_evidence":
            # Resume the existing finance worker from the unmet semantic
            # checkpoint.  Research/GitHub success is not replayed and a
            # textual completed result cannot close the evidence gap.
            finance_task = next((
                task for task in plan.all_tasks()
                if task.agent == "finance" and task.handler is not None
            ), None)
            if finance_task is not None:
                finance_task.status = TaskStatus.PENDING
                finance_task.error = ""
                finance_task.result = None
                job_manager.run_task(finance_task)
                learning_task = next((
                    task for task in plan.all_tasks()
                    if task.agent == "learning" and task.handler is not None
                ), None)
                if learning_task is not None:
                    learning_task.status = TaskStatus.PENDING
                    learning_task.error = ""
                    learning_task.result = None
                    job_manager.run_task(learning_task)
                break

    remaining = evaluate_goal_completion(mission).missing
    report.remaining_goals = [item.requirement.remaining for item in remaining]
    if remaining:
        # A declared safe route means recovery can continue in a later pass.
        # Otherwise current local/free execution is exhausted and human
        # intervention/integration is required.
        safe_route_left = any(
            task.metadata.get("artifact_recovery_available") is True
            for task in plan.all_tasks()
        ) or any(
            item.requirement.kind == "finance_evidence" and any(
                task.agent == "finance" and task.handler is not None for task in plan.all_tasks()
            ) for item in remaining
        )
        report.blocked = not safe_route_left
        if report.blocked and not report.approval_required:
            report.approval_required.append({
                "task_id": "goal-artifact",
                "department": "media",
                "need": ", ".join(report.remaining_goals),
                "why": "Beklenen gerçek artifact/evidence filesystem üzerinde doğrulanamadı.",
                "why_free_insufficient": "Bildirilen güvenli/local/free artifact üretim yolu kalmadı.",
            })

    return report
