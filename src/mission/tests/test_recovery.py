from __future__ import annotations

from src.core.task_plan import TaskPlan
from src.jobs.job_manager import JobManager
from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus
from src.mission.models import Mission, MissionType
from src.mission.recovery import (
    RecoveryAttemptHistory,
    RecoveryStep,
    _candidate_providers,
    discover_for_goal,
    plan_needs_recovery,
    recover_mission,
    recover_task,
)
from src.providers.provider_manager import ProviderManager


class _FakeProvider:
    def __init__(self, available: bool = True) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available


def _provider_manager(**availability: bool) -> ProviderManager:
    """Yalnızca verilen provider isimlerini "kullanılabilir" yapan GERÇEK
    bir ``ProviderManager`` -- diğer tüm gerçek provider'lar (anahtar/
    bağlantı olmadığından) zaten kullanılamaz kalır; sahte bir ikinci
    ProviderManager sınıfı İCAT EDİLMEZ."""

    manager = ProviderManager()
    for name, available in availability.items():
        manager._providers[name] = _FakeProvider(available=available)
    return manager


def _mission(mission_type: MissionType = MissionType.RESEARCH) -> Mission:
    return Mission(title="t", description="t", mission_type=mission_type)


class TestRecoverTaskProviderFallback:
    def test_quota_exhausted_falls_back_to_alternative_free_provider(self):
        # Sprint 42 TEST A: Provider A kotası bitti, Provider B (ücretsiz)
        # müsait -- mission DURMAZ, B'ye geçilir, AYNI hedef devam eder.
        calls: list[str] = []

        def handler(task: Task):
            provider = task.metadata.get("preferred_ai_provider")
            calls.append(provider)
            if provider == "gemini":
                return "Gerçek analiz sonucu -- gemini ile üretildi."
            raise RuntimeError("insufficient_quota: you exceeded your current quota")

        task = Task(
            title="t", agent="research", handler=handler,
            metadata={"preferred_ai_provider": "openrouter"},
        )
        task.status = TaskStatus.FAILED
        task.error = "insufficient_quota: you exceeded your current quota"

        manager = _provider_manager(ollama=False, gemini=True, openrouter=True)
        mission = _mission()

        attempts = recover_task(
            task, mission,
            provider_manager=manager, job_manager=JobManager(), history=RecoveryAttemptHistory(),
        )

        assert task.status == TaskStatus.COMPLETED
        assert any(a.provider_tried == "gemini" and a.succeeded for a in attempts)
        assert calls[0] == "openrouter"  # basamak 1: önce AYNI yöntem denendi
        assert "gemini" in calls

    def test_ollama_timeout_falls_back_without_endless_blind_retry(self):
        # Sprint 42 TEST B: Ollama zaman aşımına uğradı, başka bir ücretsiz
        # yöntem var -- kör bir şekilde AYNI sağlayıcı sonsuza dek
        # denenmez, alternatif denenir.
        calls: list[str] = []

        def handler(task: Task):
            provider = task.metadata.get("preferred_ai_provider") or "ollama"
            calls.append(provider)
            if provider == "ollama":
                raise TimeoutError("Ollama zaman aşımına uğradı.")
            return "Gerçek özet metni burada."

        task = Task(
            title="t", agent="finance", handler=handler,
            metadata={"preferred_ai_provider": "ollama"},
        )
        task.status = TaskStatus.FAILED
        task.error = "Ollama zaman aşımına uğradı."

        manager = _provider_manager(ollama=True, groq=True)
        mission = _mission(MissionType.FINANCE)

        attempts = recover_task(
            task, mission,
            provider_manager=manager, job_manager=JobManager(), history=RecoveryAttemptHistory(),
        )

        assert task.status == TaskStatus.COMPLETED
        assert calls.count("ollama") == 1  # sonsuza dek tekrarlanmadı
        assert "groq" in calls
        assert [a.step for a in attempts] == [
            RecoveryStep.SAME_METHOD_RETRY, RecoveryStep.ANOTHER_FREE_PROVIDER,
        ]

    def test_same_method_retry_does_not_shrink_below_the_department_budget(self):
        # Sprint: research/production pipeline audit -- a real Swiss Insider
        # mission run failed with "Task timed out (20.0 sec)": the OLD
        # _rerun() unconditionally shrank ANY timeout-classified same-method
        # retry to a flat 20s (min(original_timeout or 20.0, 20.0)) --
        # smaller than even ONE inner provider call's own timeout, so a
        # genuinely slow-but-correct department (research, sized to its own
        # real worst-case, see test_research_department_timeout.py) was
        # GUARANTEED a second, faster failure on retry. The retry window is
        # now bounded by Settings.RECOVERY_SAME_METHOD_RETRY_TIMEOUT_SECONDS
        # (default 300s -- large enough to never bind below a real
        # department budget) instead of a flat magic number.
        seen_timeouts: list[float] = []

        def handler(task: Task):
            seen_timeouts.append(task.timeout_seconds)
            if len(seen_timeouts) == 1:
                raise TimeoutError("Görev zaman aşımına uğradı (165.0 sn).")
            return "Araştırma tamamlandı."

        task = Task(title="t", agent="research", handler=handler, timeout_seconds=165.0)
        task.status = TaskStatus.FAILED
        task.error = "Görev zaman aşımına uğradı (165.0 sn)."

        manager = _provider_manager(ollama=True)
        mission = _mission(MissionType.RESEARCH)

        attempts = recover_task(
            task, mission,
            provider_manager=manager, job_manager=JobManager(), history=RecoveryAttemptHistory(),
        )

        assert len(seen_timeouts) >= 2
        # NOT shrunk to the old broken flat 20.0 -- the retry got (at
        # least) the same real budget the first attempt had.
        assert seen_timeouts[1] == 165.0
        assert task.status == TaskStatus.COMPLETED
        assert task.timeout_seconds == 165.0  # restored after the retry, unchanged for future callers
        assert attempts[0].step == RecoveryStep.SAME_METHOD_RETRY

    def test_same_method_retry_timeout_is_bounded_by_the_configured_retry_cap(self, monkeypatch):
        # The retry window is configurable/bounded, not unconditionally
        # equal to the original timeout -- a department with an enormous
        # original budget still gets capped at
        # Settings.RECOVERY_SAME_METHOD_RETRY_TIMEOUT_SECONDS.
        from src.config.settings import Settings
        monkeypatch.setattr(Settings, "RECOVERY_SAME_METHOD_RETRY_TIMEOUT_SECONDS", 30.0)
        seen_timeouts: list[float] = []

        def handler(task: Task):
            seen_timeouts.append(task.timeout_seconds)
            if len(seen_timeouts) == 1:
                raise TimeoutError("Görev zaman aşımına uğradı (500.0 sn).")
            return "tamam"

        task = Task(title="t", agent="research", handler=handler, timeout_seconds=500.0)
        task.status = TaskStatus.FAILED
        task.error = "Görev zaman aşımına uğradı (500.0 sn)."

        manager = _provider_manager(ollama=True)
        recover_task(task, _mission(MissionType.RESEARCH), provider_manager=manager,
                     job_manager=JobManager(), history=RecoveryAttemptHistory())

        assert seen_timeouts[1] == 30.0  # capped, never the full 500s
        assert seen_timeouts[1] > 20.0  # still well above the old broken flat cap

    def test_non_recoverable_failure_is_not_retried_with_different_provider(self):
        # "handler tanımlı değil" gibi TOOL_FAILURE bir provider değişimiyle
        # ÇÖZÜLEMEZ -- ladder hiç tetiklenmemeli.
        calls: list[str] = []

        def handler(task: Task):
            calls.append("called")
            return "ok"

        task = Task(title="t", agent="automation", handler=handler, metadata={})
        task.status = TaskStatus.FAILED
        task.error = "Görev için handler tanımlı değil."

        attempts = recover_task(
            task, _mission(),
            provider_manager=_provider_manager(ollama=True), job_manager=JobManager(),
            history=RecoveryAttemptHistory(),
        )

        assert attempts == []
        assert calls == []
        assert task.status == TaskStatus.FAILED

    def test_no_handler_returns_no_attempts(self):
        task = Task(title="t", agent="media", handler=None)
        task.status = TaskStatus.FAILED
        task.error = "Ollama zaman aşımına uğradı."

        attempts = recover_task(
            task, _mission(),
            provider_manager=_provider_manager(ollama=True), job_manager=JobManager(),
            history=RecoveryAttemptHistory(),
        )

        assert attempts == []


class TestPaidBoundary:
    def test_only_paid_left_never_called_reaches_approval_required(self):
        # Sprint 42 TEST D: tüm ücretsiz seçenekler tükendi, yalnızca
        # ücretli kaldı -- ücretli sağlayıcı ASLA çağrılmaz, kullanıcı
        # onayı gerektiren bir duruma geçilir.
        calls: list[str] = []

        def handler(task: Task):
            calls.append(task.metadata.get("preferred_ai_provider"))
            raise RuntimeError("429 Too Many Requests")

        task = Task(
            title="t", agent="research", handler=handler,
            metadata={"preferred_ai_provider": "groq"},
        )
        task.status = TaskStatus.FAILED
        task.error = "429 Too Many Requests"

        manager = _provider_manager(
            ollama=False, gemini=False, groq=True, openrouter=False, openai=True,
        )
        mission = _mission()

        attempts = recover_task(
            task, mission,
            provider_manager=manager, job_manager=JobManager(), history=RecoveryAttemptHistory(),
        )

        assert task.status == TaskStatus.FAILED
        assert "openai" not in calls  # ücretli sağlayıcı ASLA çağrılmadı
        assert attempts[-1].step == RecoveryStep.PAID_APPROVAL_REQUIRED
        assert "ücretli" in attempts[-1].note


class TestRecoverMissionCheckpoint:
    def test_only_failed_step_reruns_completed_steps_untouched(self):
        # Sprint 42 TEST C: 3 adımlı mission, 1-2 başarılı, 3 başarısız --
        # kurtarma SONRASI yalnızca adım 3 yeniden çalışır.
        calls = {"step1": 0, "step2": 0, "step3": 0}

        def make_handler(name: str):
            def handler(task: Task):
                calls[name] += 1
                return f"{name} tamamlandı"
            return handler

        plan = TaskPlan(goal="t")

        t1 = Task(title="adım1", agent="github", handler=make_handler("step1"))
        t1.status = TaskStatus.COMPLETED
        t1.result = TaskResult(success=True, output="adım1 tamamlandı")
        plan.add_task(t1)

        t2 = Task(title="adım2", agent="evaluation", handler=make_handler("step2"))
        t2.status = TaskStatus.COMPLETED
        t2.result = TaskResult(success=True, output="adım2 tamamlandı")
        plan.add_task(t2, depends_on=[t1])

        t3 = Task(title="adım3", agent="media", handler=make_handler("step3"))
        t3.status = TaskStatus.FAILED
        t3.error = "Ollama zaman aşımına uğradı."
        plan.add_task(t3, depends_on=[t2])

        mission = _mission(MissionType.YOUTUBE)
        mission.tasks = [t1, t2, t3]

        report = recover_mission(mission, plan, provider_manager=_provider_manager(ollama=True))

        assert t3.status == TaskStatus.COMPLETED
        assert calls == {"step1": 0, "step2": 0, "step3": 1}
        assert report.resolved_task_ids == [t3.id]
        assert t1.status == TaskStatus.COMPLETED
        assert t2.status == TaskStatus.COMPLETED

    def test_cancelled_dependents_of_recovered_task_resume(self):
        # Kurtarılan bir görev sayesinde daha önce CANCELLED kalmış bir
        # bağımlı görev de otomatik olarak devam ETMELİDİR (checkpoint).
        calls = {"step1": 0, "step2": 0}

        plan = TaskPlan(goal="t")

        t1 = Task(title="adım1", agent="media", handler=lambda t: (calls.__setitem__("step1", calls["step1"] + 1), "tamam")[1])
        t1.status = TaskStatus.FAILED
        t1.error = "Ollama zaman aşımına uğradı."
        plan.add_task(t1)

        t2 = Task(title="adım2", agent="automation", handler=lambda t: (calls.__setitem__("step2", calls["step2"] + 1), "tamam")[1])
        t2.status = TaskStatus.CANCELLED
        plan.add_task(t2, depends_on=[t1])

        mission = _mission(MissionType.YOUTUBE)
        mission.tasks = [t1, t2]

        report = recover_mission(mission, plan, provider_manager=_provider_manager(ollama=True))

        assert t1.status == TaskStatus.COMPLETED
        assert t2.status == TaskStatus.COMPLETED
        assert calls == {"step1": 1, "step2": 1}
        assert t2.id in report.resumed_task_ids


class TestGoalDrivenDiscovery:
    def test_youtube_capability_gap_triggers_video_focused_discovery_only(self):
        # Sprint 42 TEST E: YouTube video üretim yeteneği eksik -- yalnızca
        # video/TTS ile ilgili DAR bir odakla keşif yapılır.
        calls: list[tuple[str, bool]] = []

        class _FakeCollector:
            def collect(self, focus="", broad=True, **kwargs):
                calls.append((focus, broad))
                return [{"title": "OpenTTS", "url": "https://example.com/opentts"}]

        task = Task(title="t", agent="media", handler=None)
        mission = _mission(MissionType.YOUTUBE)

        outcome = discover_for_goal(mission, task, _FakeCollector())

        assert outcome.ran is True
        assert "video" in outcome.focus
        assert "finance" not in outcome.focus
        assert "coding" not in outcome.focus
        assert calls == [(outcome.focus, False)]  # broad=False -- 5 sabit sorgu ATLANDI
        assert outcome.candidates

    def test_capability_that_already_exists_does_not_trigger_discovery(self):
        # Sprint 42 TEST F: görevin arkasında GERÇEK bir handler VARSA
        # (yetenek zaten mevcut, hata yalnızca provider kaynaklı) --
        # recover_mission keşfi hiç TETİKLEMEZ.
        calls: list[str] = []

        def handler(task: Task):
            calls.append("handler-called")
            raise RuntimeError("insufficient_quota: exceeded")

        class _FakeCollector:
            def collect(self, **kwargs):
                calls.append("discovery-called")
                return []

        task = Task(title="t", agent="finance", handler=handler, metadata={})
        task.status = TaskStatus.FAILED
        task.error = "insufficient_quota: exceeded"

        plan = TaskPlan(goal="t")
        plan.add_task(task)
        mission = _mission(MissionType.FINANCE)
        mission.tasks = [task]

        manager = _provider_manager(ollama=False, gemini=False, groq=False, openrouter=False)

        report = recover_mission(
            mission, plan, provider_manager=manager, evolution_collector=_FakeCollector(),
        )

        assert report.discovery_runs == []
        assert "discovery-called" not in calls

    def test_undefined_mission_type_focus_does_not_run_discovery(self):
        task = Task(title="t", agent="social_media", handler=None)
        mission = _mission(MissionType.SECURITY)
        mission.mission_type = MissionType.RESEARCH  # odak tablosunda YOK varsayımı test edilir

        class _FakeCollector:
            def collect(self, **kwargs):
                raise AssertionError("çağrılmamalı")

        # RESEARCH _DISCOVERY_FOCUS_BY_MISSION_TYPE'ta tanımlı DEĞİL.
        outcome = discover_for_goal(mission, task, _FakeCollector())

        assert outcome.ran is False
        assert outcome.candidates == []


class TestNoInfiniteLoop:
    def test_second_recovery_call_after_ladder_exhausted_makes_no_new_handler_calls(self):
        # Sprint 42 TEST I: aynı (görev + hata) tekrar kurtarmaya
        # sunulsa bile -- ladder tükendikten sonra hiçbir YENİ handler
        # çağrısı yapılmaz (sonsuz döngü YOK).
        calls: list[str] = []

        def handler(task: Task):
            calls.append(task.metadata.get("preferred_ai_provider"))
            raise RuntimeError("Model bulunamadı.")

        task = Task(
            title="t", agent="research", handler=handler,
            metadata={"preferred_ai_provider": "ollama"},
        )
        task.status = TaskStatus.FAILED
        task.error = "Model bulunamadı."

        manager = _provider_manager(ollama=True)
        mission = _mission()
        history = RecoveryAttemptHistory()

        first_attempts = recover_task(
            task, mission, provider_manager=manager, job_manager=JobManager(), history=history,
        )
        calls_after_first = len(calls)

        assert calls_after_first >= 1
        assert first_attempts[-1].step == RecoveryStep.PAID_APPROVAL_REQUIRED

        task.status = TaskStatus.FAILED  # üst seviye kod tekrar çağırırsa simülasyonu
        second_attempts = recover_task(
            task, mission, provider_manager=manager, job_manager=JobManager(), history=history,
        )

        assert len(calls) == calls_after_first  # hiç yeni çağrı YOK
        assert second_attempts == []


class TestCandidateProviderOrdering:
    def test_department_fallback_provider_is_tried_first(self):
        from src.strategy.models import AIChoice, AIStrategyPlan, DepartmentChoice, TaskCategory, ToolChoice

        mission = _mission(MissionType.FINANCE)
        base_choice = AIChoice(
            provider="ollama", model="m", tier="1", reason="t",
            estimated_cost=0.0, confidence=80,
        )
        mission.ai_strategy = AIStrategyPlan(
            request="t", category=TaskCategory.FINANCE, category_reason="t",
            departments=(DepartmentChoice(name="finance", reason="t"),),
            tools=(ToolChoice(name="t", reason="t"),),
            ai_choice=base_choice,
            free_sufficient=True, free_sufficient_reason="t",
            local_sufficient=True, local_sufficient_reason="t",
            paid_required=False, paid_required_reason="t",
            department_ai_choices={
                "finance": AIChoice(
                    provider="ollama", model="m", tier="1", reason="t",
                    estimated_cost=0.0, confidence=80, fallback_provider="groq",
                ),
            },
        )
        task = Task(
            title="t", agent="finance", handler=lambda t: "x",
            metadata={"preferred_ai_provider": "ollama"},
        )
        manager = _provider_manager(ollama=True, gemini=True, groq=True)

        candidates = _candidate_providers(manager, mission, task, already_tried=set())

        assert candidates[0] == "groq"


class TestFalseSuccessRecovery:
    """Sprint 43 (FALSE SUCCESS RECOVERY): ``TaskStatus.COMPLETED``
    görünüp GERÇEK bir çıktı üretmemiş görevler de kurtarmaya girmeli --
    yalnızca klasik ``TaskStatus.FAILED`` DEĞİL."""

    def test_a_completed_with_timeout_text_is_not_success_and_triggers_recovery(self):
        calls: list[str] = []

        def handler(task: Task):
            provider = task.metadata.get("preferred_ai_provider")
            calls.append(provider)
            if provider == "gemini":
                return "Gerçek analiz sonucu -- gemini ile üretildi."
            return "Ollama zaman aşımına uğradı."

        plan = TaskPlan(goal="t")
        task = Task(
            title="t", agent="finance", handler=handler,
            metadata={"preferred_ai_provider": "ollama"},
        )
        task.status = TaskStatus.COMPLETED
        task.result = TaskResult(success=True, output="Ollama zaman aşımına uğradı.")
        plan.add_task(task)

        mission = _mission(MissionType.FINANCE)
        mission.tasks = [task]

        assert plan_needs_recovery(plan) is True

        report = recover_mission(
            mission, plan, provider_manager=_provider_manager(ollama=True, gemini=True),
        )

        assert report.ran is True
        assert task.status == TaskStatus.COMPLETED
        assert task.result.output == "Gerçek analiz sonucu -- gemini ile üretildi."
        assert task.id in report.resolved_task_ids
        assert plan_needs_recovery(plan) is False

    def test_b_completed_with_quota_text_classified_and_falls_back_to_free_provider(self):
        def handler(task: Task):
            provider = task.metadata.get("preferred_ai_provider")
            if provider == "groq":
                return "Gerçek piyasa özeti."
            return "429 quota exceeded"

        task = Task(
            title="t", agent="research", handler=handler,
            metadata={"preferred_ai_provider": "openrouter"},
        )
        task.status = TaskStatus.COMPLETED
        task.result = TaskResult(success=True, output="429 quota exceeded")

        from src.mission.failure_classification import FailureClass, classify_failure

        assert classify_failure("429 quota exceeded") in (
            FailureClass.RATE_LIMIT, FailureClass.QUOTA_EXHAUSTED,
        )

        attempts = recover_task(
            task, _mission(),
            provider_manager=_provider_manager(ollama=False, groq=True, openrouter=True),
            job_manager=JobManager(), history=RecoveryAttemptHistory(),
        )

        assert task.status == TaskStatus.COMPLETED
        assert task.result.output == "Gerçek piyasa özeti."
        assert any(a.provider_tried == "groq" and a.succeeded for a in attempts)

    def test_c_completed_with_real_content_never_triggers_recovery(self):
        task = Task(title="t", agent="research", handler=lambda t: "ok")
        task.status = TaskStatus.COMPLETED
        task.result = TaskResult(success=True, output="Gerçek, uzun ve anlamlı bir araştırma özeti.")

        plan = TaskPlan(goal="t")
        plan.add_task(task)

        assert plan_needs_recovery(plan) is False

        report = recover_mission(_mission(), plan, provider_manager=_provider_manager(ollama=True))

        assert report.ran is False
        assert report.attempts == []

    def test_d_false_success_dependent_reruns_but_unrelated_completed_task_does_not(self):
        # Research GERÇEKTEN tamamlandı, Media sahte-başarı, Integration
        # Media'ya bağımlı -- Research YENİDEN ÇALIŞMAMALI, Media
        # kurtarılmalı, SONRA yalnızca Integration (gerçek bağımlı) devam
        # etmeli.
        calls = {"research": 0, "media": 0, "integration": 0}

        def research_handler(task: Task):
            calls["research"] += 1
            return "araştırma çıktısı"

        def media_handler(task: Task):
            calls["media"] += 1
            provider = task.metadata.get("preferred_ai_provider")
            if provider == "gemini":
                return "GERÇEK senaryo metni burada."
            return "Ollama zaman aşımına uğradı."

        def integration_handler(task: Task):
            calls["integration"] += 1
            return "entegrasyon planı hazır"

        plan = TaskPlan(goal="t")

        research = Task(title="research", agent="research", handler=research_handler)
        research.status = TaskStatus.COMPLETED
        research.result = TaskResult(success=True, output="araştırma çıktısı")
        plan.add_task(research)

        media = Task(
            title="media", agent="media", handler=media_handler,
            metadata={"preferred_ai_provider": "ollama"},
        )
        media.status = TaskStatus.COMPLETED
        media.result = TaskResult(success=True, output="Ollama zaman aşımına uğradı.")
        plan.add_task(media, depends_on=[research])

        # Integration, Media'nın (o an GEÇERLİ görünen) COMPLETED durumu
        # sayesinde ZATEN çalışmış -- bozuk veriyle "başarılı" tamamlandı
        # (gerçek IntegrationPlanner tamamen deterministik olduğu için
        # kendi çıktısı bir LLM-hata işareti TAŞIMAZ).
        integration = Task(title="integration", agent="integration", handler=integration_handler)
        integration.status = TaskStatus.COMPLETED
        integration.result = TaskResult(success=True, output="entegrasyon planı hazır (ESKİ/BOZUK veriyle)")
        plan.add_task(integration, depends_on=[media])

        mission = _mission(MissionType.YOUTUBE)
        mission.tasks = [research, media, integration]

        report = recover_mission(
            mission, plan, provider_manager=_provider_manager(ollama=True, gemini=True),
        )

        assert calls["research"] == 0  # gerçekten tamamlanmış görev asla yeniden ÇAĞRILMADI
        assert calls["media"] == 2  # basamak 1 (aynı yöntem, ollama) + basamak 2/3 (gemini)
        assert calls["integration"] == 1  # yalnızca GEREKLİ bağımlı, TEK KEZ yeniden çalıştı

        assert media.status == TaskStatus.COMPLETED
        assert media.result.output == "GERÇEK senaryo metni burada."
        assert integration.status == TaskStatus.COMPLETED
        assert integration.result.output == "entegrasyon planı hazır"
        assert media.id in report.resolved_task_ids
        assert integration.id in report.resumed_task_ids

    def test_e_no_free_alternative_left_reaches_approval_required_without_paid_call(self):
        calls: list[str] = []

        def handler(task: Task):
            calls.append(task.metadata.get("preferred_ai_provider"))
            return "Model bulunamadı."

        task = Task(
            title="t", agent="research", handler=handler,
            metadata={"preferred_ai_provider": "ollama"},
        )
        task.status = TaskStatus.COMPLETED
        task.result = TaskResult(success=True, output="Model bulunamadı.")

        plan = TaskPlan(goal="t")
        plan.add_task(task)
        mission = _mission()
        mission.tasks = [task]

        manager = _provider_manager(ollama=True, gemini=False, groq=False, openrouter=False, openai=True)

        report = recover_mission(mission, plan, provider_manager=manager)

        assert task.status == TaskStatus.COMPLETED  # hâlâ "tamamlandı" görünür ama...
        assert plan_needs_recovery(plan) is True  # ...GERÇEKTEN başarılı SAYILMAZ
        assert "openai" not in calls  # ücretli sağlayıcı ASLA çağrılmadı
        assert report.approval_required
        assert report.approval_required[0]["task_id"] == task.id

    def test_f_repeated_false_success_does_not_loop_forever(self):
        calls: list[str] = []

        def handler(task: Task):
            calls.append(task.metadata.get("preferred_ai_provider"))
            return "Model bulunamadı."

        task = Task(
            title="t", agent="research", handler=handler,
            metadata={"preferred_ai_provider": "ollama"},
        )
        task.status = TaskStatus.COMPLETED
        task.result = TaskResult(success=True, output="Model bulunamadı.")

        plan = TaskPlan(goal="t")
        plan.add_task(task)
        mission = _mission()
        mission.tasks = [task]
        manager = _provider_manager(ollama=True)
        history = RecoveryAttemptHistory()

        first_report = recover_mission(mission, plan, provider_manager=manager, history=history)
        calls_after_first = len(calls)
        assert calls_after_first >= 1

        # AYNI (hâlâ sahte-başarılı) görev tekrar kurtarmaya sunulsa bile
        # -- hiçbir YENİ handler çağrısı yapılmaz (sonsuz döngü YOK).
        second_report = recover_mission(mission, plan, provider_manager=manager, history=history)

        assert len(calls) == calls_after_first
        assert second_report.attempts == []
        assert first_report.approval_required


class TestClaudeCodeRecoveryConnection:
    """Sprint 44 (CLAUDE CODE WORKER BRIDGE bölüm 8/9/14): claude_code
    ``AUTO_SAFE_PROVIDERS``'a EKLENMEDİ (bkz. recovery.py) -- bu yüzden
    ZATEN VAR OLAN kurtarma merdiveni, Claude Code'u hem "başarısız olan
    provider" hem de "asla otomatik seçilmeyecek ücretli-benzeri kaynak"
    olarak doğru ele almalı, ikinci bir kurtarma sistemi OLMADAN."""

    def test_f_original_goal_never_mutates_after_claude_code_failure(self):
        # Sprint 44 bölüm 9: "Claude'u tekrar çalıştır" gibi bir meta-hedefe
        # ASLA dönüşmemeli -- orijinal hedef metni baştan sona AYNI kalır.
        def handler(task: Task):
            provider = task.metadata.get("preferred_ai_provider")
            if provider == "ollama":
                return "Gerçek düzeltme önerisi burada."
            return "Claude Code kullanım kotası aşıldı (limit aşıldı): session limit reached."

        original_title = "Provider routing bug'ını düzelt."
        task = Task(
            title=original_title, agent="research", handler=handler,
            metadata={"preferred_ai_provider": "claude_code"},
        )
        task.status = TaskStatus.FAILED
        task.error = "Claude Code kullanım kotası aşıldı (limit aşıldı): session limit reached."

        mission = _mission()
        mission.title = original_title
        mission.goal = original_title

        attempts = recover_task(
            task, mission,
            provider_manager=_provider_manager(ollama=True), job_manager=JobManager(),
            history=RecoveryAttemptHistory(),
        )

        assert task.title == original_title  # görev hiç yeniden adlandırılmadı
        assert mission.title == original_title  # hedef metni MUTASYONA UĞRAMADI
        assert mission.goal == original_title
        assert any(a.succeeded for a in attempts)

    def test_g_claude_code_quota_exhausted_falls_back_to_free_local_alternative(self):
        # TEST G: Claude Code kotası bitti, yerel/ücretsiz alternatif VAR --
        # mission DURMAZ.
        calls: list[str] = []

        def handler(task: Task):
            provider = task.metadata.get("preferred_ai_provider")
            calls.append(provider)
            if provider == "ollama":
                return "Gerçek analiz -- ollama ile üretildi."
            return "Claude Code kullanım kotası aşıldı (limit aşıldı)."

        task = Task(
            title="t", agent="research", handler=handler,
            metadata={"preferred_ai_provider": "claude_code"},
        )
        task.status = TaskStatus.FAILED
        task.error = "Claude Code kullanım kotası aşıldı (limit aşıldı)."

        attempts = recover_task(
            task, _mission(),
            provider_manager=_provider_manager(ollama=True), job_manager=JobManager(),
            history=RecoveryAttemptHistory(),
        )

        assert task.status == TaskStatus.COMPLETED
        assert "ollama" in calls
        assert "claude_code" not in _candidate_providers(
            _provider_manager(ollama=True), _mission(), task, already_tried=set(),
        )  # claude_code hiçbir zaman OTOMATİK aday olarak önerilmez

    def test_h_claude_code_unavailable_only_paid_left_no_automatic_paid_call(self):
        # TEST H: Claude Code kullanılamıyor, geriye yalnızca ücretli bir
        # API alternatifi (openai) kaldı -- OTOMATİK çağrılmaz.
        calls: list[str] = []

        def handler(task: Task):
            calls.append(task.metadata.get("preferred_ai_provider"))
            raise RuntimeError("Claude Code CLI bulunamadı (PATH'te \"claude\" yok).")

        task = Task(
            title="t", agent="research", handler=handler,
            metadata={"preferred_ai_provider": "claude_code"},
        )
        task.status = TaskStatus.FAILED
        task.error = "Claude Code CLI bulunamadı (PATH'te \"claude\" yok)."

        manager = _provider_manager(
            ollama=False, gemini=False, groq=False, openrouter=False, openai=True,
        )

        attempts = recover_task(
            task, _mission(),
            provider_manager=manager, job_manager=JobManager(), history=RecoveryAttemptHistory(),
        )

        assert task.status == TaskStatus.FAILED
        assert "openai" not in calls
        assert attempts[-1].step == RecoveryStep.PAID_APPROVAL_REQUIRED
