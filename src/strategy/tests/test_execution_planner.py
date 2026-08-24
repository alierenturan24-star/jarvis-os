from __future__ import annotations

from src.jobs.task import Task
from src.jobs.task_status import TaskStatus
from src.mission.models import Mission
from src.strategy.execution_planner import build_execution_plan, build_self_check
from src.strategy.models import (
    AIChoice,
    AIStrategyPlan,
    DepartmentChoice,
    SelfImprovementReview,
    TaskCategory,
    ToolChoice,
)


def _ai_strategy_plan(departments: tuple[str, ...], tier: str = "1-yerel-ücretsiz", free: bool = True) -> AIStrategyPlan:
    return AIStrategyPlan(
        request="test",
        category=TaskCategory.YOUTUBE,
        category_reason="test",
        departments=tuple(DepartmentChoice(name=name, reason=f"{name} gerekli") for name in departments),
        tools=tuple(ToolChoice(name=f"tool-{name}", reason="test") for name in departments),
        ai_choice=AIChoice(
            provider="ollama", model="llama3.2", tier=tier, reason="test gerekçe",
            estimated_cost=0.0 if free else 0.006, confidence=80,
        ),
        free_sufficient=free,
        free_sufficient_reason="test",
        local_sufficient=free,
        local_sufficient_reason="test",
        paid_required=not free,
        paid_required_reason="test",
    )


class TestBuildExecutionPlan:
    def test_none_plan_returns_none(self):
        assert build_execution_plan(None, "LOW") is None

    def test_steps_cover_all_departments(self):
        plan = build_execution_plan(_ai_strategy_plan(("browser", "research", "github")), "MEDIUM")
        assert plan is not None
        assert {s.department for s in plan.steps} == {"browser", "research", "github"}

    def test_steps_are_ordered_by_logical_pipeline_not_input_order(self):
        # Girdi sırası kasıtlı olarak KARIŞIK -- çıktı MANTIKSAL sıraya
        # (research -> github -> ... -> integration) göre dizilmeli.
        plan = build_execution_plan(
            _ai_strategy_plan(("integration", "github", "research", "sandbox", "evaluation")), "LOW",
        )
        names_in_order = [s.department for s in plan.steps]
        assert names_in_order == ["research", "github", "evaluation", "sandbox", "integration"]

    def test_only_research_and_finance_use_ai(self):
        plan = build_execution_plan(_ai_strategy_plan(("research", "finance", "github", "sandbox")), "LOW")
        uses_ai = {s.department: s.uses_ai for s in plan.steps}
        assert uses_ai["research"] is True
        assert uses_ai["finance"] is True
        assert uses_ai["github"] is False
        assert uses_ai["sandbox"] is False

    def test_deterministic_steps_note_no_ai_needed(self):
        plan = build_execution_plan(_ai_strategy_plan(("github",)), "LOW")
        assert "AI gerekmiyor" in plan.steps[0].ai_note

    def test_ai_step_notes_chosen_provider_and_tier(self):
        plan = build_execution_plan(_ai_strategy_plan(("research",)), "LOW")
        assert "ollama" in plan.steps[0].ai_note
        assert "1-yerel-ücretsiz" in plan.steps[0].ai_note

    def test_risk_and_cost_carried_through(self):
        plan = build_execution_plan(_ai_strategy_plan(("research",), tier="5-ücretli", free=False), "HIGH")
        assert plan.risk_level == "HIGH"
        assert plan.estimated_cost == 0.006
        assert "Ücretli katman" in plan.cost_note

    def test_free_tier_cost_note_says_no_extra_cost(self):
        plan = build_execution_plan(_ai_strategy_plan(("research",)), "LOW")
        assert "ek maliyet yok" in plan.cost_note

    def test_unmapped_department_still_gets_a_tool_placeholder(self):
        # Sprint 39: media/automation artık GERÇEK modüllere bağlı (bkz.
        # _TOOLS_FOR_DEPARTMENT) -- "social_media" gibi hâlâ bağlı olmayan
        # departmanlar için de (dürüstçe) bir tool notu üretilmeli, çökme
        # OLMAMALI.
        plan = build_execution_plan(_ai_strategy_plan(("social_media",)), "LOW")
        assert plan.steps[0].tool == "(social_media)"


def _task(agent: str, *, status=TaskStatus.COMPLETED, handler=lambda t: "ok", metadata=None, output="") -> Task:
    from src.jobs.task_result import TaskResult

    task = Task(title=f"[{agent}]", agent=agent, target="x", handler=handler, metadata=metadata or {})
    task.status = status
    if output:
        task.result = TaskResult(output=output, success=True)
    return task


class TestBuildSelfCheck:
    def test_success_rate_all_completed(self):
        mission = Mission(title="t")
        mission.tasks = [_task("research"), _task("github")]
        check = build_self_check(mission, review=None)
        assert check.success_rate == 100.0

    def test_success_rate_partial(self):
        mission = Mission(title="t")
        mission.tasks = [_task("research"), _task("github", status=TaskStatus.FAILED)]
        check = build_self_check(mission, review=None)
        assert check.success_rate == 50.0

    def test_no_tasks_zero_percent(self):
        mission = Mission(title="t")
        mission.tasks = []
        check = build_self_check(mission, review=None)
        assert check.success_rate == 0.0

    def test_unconnected_department_reported_as_missing_info(self):
        mission = Mission(title="t")
        mission.tasks = [_task("media", handler=None, status=TaskStatus.FAILED)]
        check = build_self_check(mission, review=None)
        assert any("media" in item for item in check.missing_info)

    def test_failed_task_reported_as_missing_info(self):
        mission = Mission(title="t")
        mission.tasks = [_task("github", status=TaskStatus.FAILED)]
        check = build_self_check(mission, review=None)
        assert any("github" in item and "tamamlanmadı" in item for item in check.missing_info)

    def test_cached_research_detected_via_existing_manager_marker(self):
        # ResearchManager ZATEN "Bu konu daha önce araştırılmış." metnini
        # üretiyor (bkz. src/research/manager.py) -- yeni bir önbellek
        # mekanizması İCAT EDİLMEDİ, yalnızca bu GERÇEK işaret okunuyor.
        # Not: research task'ları (github/evaluation/sandbox/integration'ın
        # AKSİNE) ``metadata["report"]`` YAZMAZ -- metadata=None/boş,
        # Sprint 36 canlı testinde yakalanan bir hatayı kapsamak için
        # bilerek BOŞ bırakıldı (bkz. execution_planner.py'deki not).
        mission = Mission(title="t")
        mission.tasks = [_task(
            "research",
            output="Bu konu daha önce araştırılmış.\n\nKonu: x",
        )]
        check = build_self_check(mission, review=None)
        assert check.was_cached_research is True
        assert "önbellekten geldi" in check.cache_note

    def test_fresh_research_not_marked_as_cached(self):
        mission = Mission(title="t")
        mission.tasks = [_task("research", output="Araştırma tamamlandı.\n\nyeni bulgular")]
        check = build_self_check(mission, review=None)
        assert check.was_cached_research is False
        assert "yeni bir arama yaptı" in check.cache_note

    def test_research_without_metadata_report_still_detected(self):
        # Regresyon (Sprint 36 canlı testte yakalandı): ResearchAgent
        # task.metadata["report"] YAZMADIĞI için, self-check bunu
        # ``report`` şartına BAĞLI OLMADAN tespit edebilmeli.
        mission = Mission(title="t")
        research_task = _task("research", metadata={}, output="Araştırma tamamlandı.\n\nbulgular")
        assert research_task.metadata.get("report") is None
        mission.tasks = [research_task]
        check = build_self_check(mission, review=None)
        assert check.cache_note != "Research bu mission'da çalışmadı (veri yok)."

    def test_research_result_wrapped_in_real_agent_result_does_not_crash(self):
        # Regresyon (Sprint 36 canlı testte yakalandı): task.result.output
        # DÜZ STRING DEĞİL -- BaseAgent.run()'ın sardığı gerçek bir
        # ``AgentResult`` nesnesidir (bkz. src/agents/base_agent.py).
        # ``"x" in output`` doğrudan AgentResult üzerinde ÇÖKÜYORDU
        # ("TypeError: argument of type 'AgentResult' is not iterable").
        from src.agents.agent_result import AgentResult
        from src.jobs.task_result import TaskResult

        mission = Mission(title="t")
        research_task = _task("research", metadata={})
        research_task.result = TaskResult(
            output=AgentResult(agent="Research Agent", success=True, output="Bu konu daha önce araştırılmış.\n\nx"),
            success=True,
        )
        mission.tasks = [research_task]

        check = build_self_check(mission, review=None)  # çökmemeli

        assert check.was_cached_research is True
        assert "önbellekten geldi" in check.cache_note

    def test_sandbox_fail_flags_reresearch(self):
        from src.sandbox.models import SandboxResult, SandboxStatus

        result = SandboxResult(
            repository_name="x/y", repository_url="https://github.com/x/y",
            status=SandboxStatus.BLOCKED, recommended_action="reddedildi",
        )
        from src.github.models import RepoData
        repo = RepoData(
            name="y", full_name="x/y", url="https://github.com/x/y", description="", stars=1,
            forks=0, license="mit", last_update="2026-01-01T00:00:00Z", language="Python", category="ai agent",
        )

        mission = Mission(title="t")
        mission.tasks = [_task("sandbox", metadata={"report": {"result": result, "repo": repo}})]
        check = build_self_check(mission, review=None)
        assert any("x/y" in item for item in check.needs_reresearch)

    def test_completed_task_with_failure_text_output_is_not_counted_as_success(self):
        # Sprint 42 TEST G: "Ollama zaman aşımına uğradı." bir STRING
        # döndürdü diye (Sprint 41'in temiz-timeout düzeltmesinden sonra
        # görev JobManager düzeyinde "tamamlandı" sayılıyor) success_rate
        # buna göre yanıltıcı şekilde %100 GÖSTERMEMELİ.
        mission = Mission(title="t")
        mission.tasks = [_task("media", output="Ollama zaman aşımına uğradı.")]
        check = build_self_check(mission, review=None)
        assert check.success_rate == 0.0
        assert any("gerçek içerik üretilemedi" in item for item in check.missing_info)

    def test_completed_task_with_real_output_still_counts_as_success(self):
        mission = Mission(title="t")
        mission.tasks = [_task("media", output="SENARYO\nGerçek bir içerik burada.")]
        check = build_self_check(mission, review=None)
        assert check.success_rate == 100.0
        assert check.missing_info == ()

    def test_mixed_real_and_failure_output_success_rate_reflects_only_real_ones(self):
        mission = Mission(title="t")
        mission.tasks = [
            _task("media", output="Gerçek bir içerik."),
            _task("finance", output="Ollama zaman aşımına uğradı."),
        ]
        check = build_self_check(mission, review=None)
        assert check.success_rate == 50.0

    def test_review_passthrough(self):
        review = SelfImprovementReview(
            cheaper_ai_possible=True, cheaper_ai_note="n1",
            faster_ai_possible=False, faster_ai_note="n2",
            quality_risk=False, quality_risk_note="n3",
            new_free_model_available=True, new_free_model_note="n4",
        )
        mission = Mission(title="t")
        mission.tasks = []
        check = build_self_check(mission, review=review)
        assert check.review is review
