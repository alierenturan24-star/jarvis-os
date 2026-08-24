from __future__ import annotations

from src.core.ceo import CEO
from src.evaluation.models import RepoEvaluation
from src.github.github_intelligence import GitHubIntelligence
from src.github.models import RepoData
from src.integration.integration_planner import IntegrationPlanner
from src.integration.models import IntegrationPlan
from src.jobs.task import Task
from src.jobs.task_status import TaskStatus
from src.mission.mission_engine import MissionEngine
from src.mission.models import Mission, MissionType
from src.mission.report_builder import build_ceo_report
from src.sandbox.models import SandboxResult, SandboxStatus
from src.sandbox.sandbox_manager import SandboxManager


def _repo(name: str = "octocat/sample-agent", stars: int = 4200) -> RepoData:
    return RepoData(
        name=name.split("/")[-1],
        full_name=name,
        url=f"https://github.com/{name}",
        description="An autonomous LLM agent orchestration workflow with task agents.",
        topics=["ai-agent", "llm", "orchestration", "workflow"],
        stars=stars,
        forks=10,
        license="mit",
        last_update="2026-01-01T00:00:00Z",
        language="Python",
        category="ai agent",
        open_issues=1,
        archived=False,
        contributors_count=25,
    )


def _mission_with_task(agent: str, *, status=TaskStatus.COMPLETED, handler=lambda t: "ok", metadata=None) -> Mission:
    mission = Mission(title="test mission", mission_type=MissionType.CODE, departments=[agent])
    task = Task(title=f"[{agent}] test", agent=agent, target="test", handler=handler, metadata=metadata or {})
    task.status = status
    mission.tasks = [task]
    return mission


class TestSectionsHandleMissingOrIncompleteDepartments:
    def test_department_not_selected_shows_not_selected_note(self):
        mission = Mission(title="t", mission_type=MissionType.RESEARCH, departments=["research"])
        mission.tasks = []
        report = build_ceo_report(mission)
        assert "bu mission'da bu departman seçilmedi" in report

    def test_unconnected_department_shows_no_handler_note(self):
        mission = _mission_with_task("automation", handler=None)
        report = build_ceo_report(mission)
        assert "Bağlı değil" in report

    def test_failed_task_shows_status_and_error(self):
        mission = _mission_with_task("github", status=TaskStatus.FAILED)
        mission.tasks[0].error = "boom"
        report = build_ceo_report(mission)
        assert "Tamamlanmadı" in report
        assert "boom" in report


class TestMediaSection:
    """Sprint 39: ``MediaManager``'ın (zaten var olan) çıktısı CEO
    raporunda kendi bölümünde gösterilmeli -- ``_research_section`` ile
    AYNI desen."""

    def test_media_not_selected_omits_section(self):
        mission = Mission(title="t", mission_type=MissionType.CODE, departments=["github"])
        mission.tasks = []
        report = build_ceo_report(mission)
        assert "Media" not in report

    def test_media_output_shown_in_its_own_section(self):
        from src.jobs.task_result import TaskResult

        mission = _mission_with_task("media")
        mission.tasks[0].result = TaskResult(output="SENARYO\nBitcoin düştü...", success=True)
        report = build_ceo_report(mission)
        assert "Media" in report
        assert "SENARYO" in report

    def test_media_not_duplicated_in_other_departments_section(self):
        from src.jobs.task_result import TaskResult

        mission = _mission_with_task("media")
        mission.tasks[0].result = TaskResult(output="SENARYO\n...", success=True)
        report = build_ceo_report(mission)
        assert "Diğer departmanlar" not in report


class TestReportSurfacesRealAdapterData:
    def test_github_section_shows_real_repo_rows(self):
        repo = _repo()
        mission = _mission_with_task(
            "github",
            metadata={"report": {"category": "ai agent", "total_found": 12, "top": [
                {"repo": repo, "quality_score": 88.0, "risk_score": 5.0, "reason": "Olumlu: 4,200 yıldız"},
            ]}},
        )
        report = build_ceo_report(mission)
        assert "12 repository bulundu." in report
        assert "octocat/sample-agent" in report
        assert "4,200" in report
        assert "mit" in report

    def test_evaluation_section_shows_real_validation_pipeline_table(self):
        # Sprint 18: Evaluation bölümü artık AI Validation Pipeline'ın
        # tamamını (GitHub -> Evaluation -> Sandbox -> IntegrationPlanner
        # -> CEO kararı) tek bir tabloda gösterir.
        repo = _repo()
        evaluation = RepoEvaluation(
            name="sample-agent", url="https://github.com/octocat/sample-agent",
            overall_score=82.5, architecture_score=80, activity_score=90, community_score=70,
            license_score=100, security_score=85, compatibility_score=75, maintenance_score=80,
            relevance_score=95, recommendation="ÖNERİLİR — güçlü aday.",
            suitable_for_jarvis=True, target_module="src/agents", integration_difficulty="Düşük",
            risk_level="LOW",
        )
        integration_plan = IntegrationPlan(
            repository_name="octocat/sample-agent", repository_url="https://github.com/octocat/sample-agent",
            target_module="src/agents", target_package="src/agents", integration_strategy="genişlet",
            estimated_files=5, estimated_changes=6, estimated_risk="LOW", breaking_change_probability=5.0,
            merge_ready=True, summary="ok",
        )
        candidate = {
            "repo": repo, "evaluation": evaluation, "sandbox_verdict": "PASS",
            "integration_plan": integration_plan,
        }
        mission = _mission_with_task(
            "evaluation",
            metadata={"report": {"category": "ai agent", "candidates": [candidate], "summary": {"suitable_count": 1, "count": 1}}},
        )
        report = build_ceo_report(mission)
        assert "sample-agent" in report
        assert "82" in report
        assert "ÖNERİLİR" in report
        assert "PASS" in report
        assert "Düşük" in report  # Integration Difficulty
        assert "ÖNER" in report  # CEO kararı
        assert candidate["decision"] == "ÖNER"  # section render sırasında hesaplandı

    def test_sandbox_section_shows_pass_and_real_duration_not_fabricated_cpu_ram(self):
        result = SandboxResult(
            repository_name="octocat/sample-agent", repository_url="https://github.com/octocat/sample-agent",
            status=SandboxStatus.READY_FOR_REVIEW, total_size_mb=3.2, files_scanned=40,
            detected_language="Python", recommended_action="STATIC_ANALYSIS tamamlandı.",
        )
        mission = _mission_with_task(
            "sandbox",
            metadata={"report": {"repo": _repo(), "result": result, "duration_seconds": 4.21}},
        )
        report = build_ceo_report(mission)
        assert "PASS" in report
        assert "4.21" in report
        assert "ölçülmedi" in report  # CPU/RAM fabricated edilmedi

    def test_integration_section_shows_real_migration_steps(self):
        plan = IntegrationPlan(
            repository_name="octocat/sample-agent", repository_url="https://github.com/octocat/sample-agent",
            target_module="src/agents", target_package="src/agents", integration_strategy="genişlet",
            estimated_files=12, estimated_changes=15, estimated_risk="LOW", breaking_change_probability=5.0,
            migration_steps=["Sandbox bulgularını doğrula.", "src/agents altında yeni dosya oluştur."],
            merge_ready=True, summary="octocat/sample-agent -> src/agents, Risk: LOW.",
        )
        mission = _mission_with_task("integration", metadata={"report": {"repo": _repo(), "plan": plan}})
        report = build_ceo_report(mission)
        assert "1. Sandbox bulgularını doğrula." in report
        assert "Merge'e hazır: evet" in report
        assert "~12 dosya" in report

    def test_ceo_section_present_with_recommendation_and_next_step(self):
        mission = _mission_with_task("github")
        report = build_ceo_report(mission)
        assert "CEO" in report
        assert "Öneri:" in report
        assert "Sonuç:" in report
        assert "Sonraki adım:" in report


class TestCeoReportEndToEndWithRealHandlersNetworkMocked:
    def test_develop_jarvis_report_contains_all_four_sections_with_real_data(self, monkeypatch):
        repo = _repo()
        monkeypatch.setattr(GitHubIntelligence, "search", lambda self, *a, **k: [repo])
        monkeypatch.setattr(
            SandboxManager, "run_pipeline",
            lambda self, url, evaluation, repo=None, **k: SandboxResult(
                repository_name=repo.full_name if repo else url, repository_url=url,
                status=SandboxStatus.READY_FOR_REVIEW, total_size_mb=1.0, files_scanned=5,
                recommended_action="ok",
            ),
        )
        monkeypatch.setattr(SandboxManager, "cleanup", lambda self, result: result)

        ceo = CEO()
        mission = ceo.create_mission("Jarvis'i geliştir.")
        ceo.dispatch_mission(mission)

        report = ceo.build_report(mission)

        assert "MISSION" in report
        assert "Jarvis'i geliştir." in report
        assert "Tür: CODE" in report
        assert "GitHub" in report and "octocat/sample-agent" in report
        assert "Evaluation" in report
        assert "Sandbox" in report and "PASS" in report
        assert "Integration" in report
        assert "CEO" in report


class TestAiStrategySectionShowsPerDepartmentRouting:
    """Sprint 40: mission özeti ("Seçilen provider:") DEĞİŞMEDEN, LLM
    çağıran her departman için AYRI bir satır da gösterilmeli."""

    @staticmethod
    def _strategy_plan(department_ai_choices):
        from src.strategy.models import AIChoice, AIStrategyPlan, TaskCategory

        return AIStrategyPlan(
            request="test",
            category=TaskCategory.YOUTUBE,
            category_reason="test",
            departments=(),
            tools=(),
            ai_choice=AIChoice(
                provider="ollama", model="llama3.2", tier="1-yerel-ücretsiz",
                reason="mission özeti", estimated_cost=0.0, confidence=80,
            ),
            free_sufficient=True, free_sufficient_reason="t",
            local_sufficient=True, local_sufficient_reason="t",
            paid_required=False, paid_required_reason="t",
            department_ai_choices=department_ai_choices,
        )

    def test_department_breakdown_shown_when_present(self):
        from src.strategy.models import AIChoice

        mission = Mission(title="t", mission_type=MissionType.YOUTUBE, departments=["research", "finance"])
        mission.tasks = []
        mission.ai_strategy = self._strategy_plan({
            "research": AIChoice(provider="gemini", model="gemini-2.5-flash", tier="3-ücretsiz-servis", reason="research gerekçesi", estimated_cost=0.0, confidence=88),
            "finance": AIChoice(provider="ollama", model="llama3.2", tier="1-yerel-ücretsiz", reason="finance gerekçesi", estimated_cost=0.0, confidence=65),
        })

        report = build_ceo_report(mission)

        assert "Departman başına provider kararı:" in report
        assert "research: gemini" in report
        assert "finance: ollama" in report
        # Mission özeti satırı DEĞİŞMEDEN kalmalı.
        assert "Seçilen provider: ollama" in report

    def test_no_breakdown_section_when_map_is_empty(self):
        mission = Mission(title="t", mission_type=MissionType.CODE, departments=["github"])
        mission.tasks = []
        mission.ai_strategy = self._strategy_plan({})

        report = build_ceo_report(mission)

        assert "Departman başına provider kararı:" not in report


class TestRecoverySection:
    """Sprint 42 (AUTONOMOUS GOAL EXECUTION): ``mission.recovery`` (bkz.
    ``src.mission.recovery``) CEO raporunda okunabilir bir bölüme
    dönüşmeli -- yeni bir değerlendirme İCAT ETMEZ, yalnızca ZATEN
    hesaplanmış ``MissionRecoveryReport``'u okur."""

    def test_no_recovery_shows_never_triggered_note(self):
        mission = Mission(title="t", mission_type=MissionType.CODE, departments=["github"])
        mission.tasks = []

        report = build_ceo_report(mission)

        assert "RECOVERY (HEDEF KORUMA)" in report
        assert "kurtarma hiç tetiklenmedi" in report

    def test_recovery_report_renders_goal_preservation_questions_and_attempts(self):
        from src.mission.failure_classification import FailureClass
        from src.mission.recovery import MissionRecoveryReport, RecoveryAttempt, RecoveryStep

        t1 = Task(title="[github] adım1", agent="github", handler=lambda t: "ok")
        t1.status = TaskStatus.COMPLETED
        t2 = Task(title="[media] adım2", agent="media", handler=lambda t: "ok")
        t2.status = TaskStatus.COMPLETED

        mission = Mission(title="YouTube videosu üret", mission_type=MissionType.YOUTUBE, departments=["github", "media"])
        mission.tasks = [t1, t2]
        mission.recovery = MissionRecoveryReport(
            goal="YouTube videosu üret",
            ran=True,
            attempts=[
                RecoveryAttempt(
                    task_id=t2.id, department="media", failure_class=FailureClass.TIMEOUT,
                    step=RecoveryStep.SAME_METHOD_RETRY, provider_tried="__same_method_retry__",
                    succeeded=False, note="Aynı yöntemle tekrar denendi.",
                ),
                RecoveryAttempt(
                    task_id=t2.id, department="media", failure_class=FailureClass.TIMEOUT,
                    step=RecoveryStep.ANOTHER_FREE_PROVIDER, provider_tried="gemini",
                    succeeded=True, note='Alternatif ücretsiz sağlayıcı denendi: "gemini".',
                ),
            ],
            resolved_task_ids=[t2.id],
        )

        report = build_ceo_report(mission)

        assert "ORİJİNAL HEDEF NE? YouTube videosu üret" in report
        assert "NE KALDI? hiçbir şey (tümü kurtarıldı)" in report
        assert "NEYİN BAŞARISIZ OLMASI BENİ DURDURDU? timeout" in report
        assert "gemini" in report
        assert "Kurtarılan görev sayısı: 1" in report

    def test_approval_required_section_never_implies_a_paid_call_was_made(self):
        from src.mission.failure_classification import FailureClass
        from src.mission.recovery import MissionRecoveryReport, RecoveryAttempt, RecoveryStep

        t1 = Task(title="[finance] analiz", agent="finance", handler=lambda t: "ok")
        t1.status = TaskStatus.FAILED

        mission = Mission(title="bitcoin analiz et", mission_type=MissionType.FINANCE, departments=["finance"])
        mission.tasks = [t1]
        mission.recovery = MissionRecoveryReport(
            goal="bitcoin analiz et",
            ran=True,
            attempts=[
                RecoveryAttempt(
                    task_id=t1.id, department="finance", failure_class=FailureClass.RATE_LIMIT,
                    step=RecoveryStep.PAID_APPROVAL_REQUIRED, provider_tried="__ladder_exhausted__",
                    succeeded=False, note="Tüm ücretsiz seçenekler tükendi.",
                ),
            ],
            still_failed_task_ids=[t1.id],
            approval_required=[{
                "task_id": t1.id, "department": "finance",
                "need": '"finance" görevi için ücretli bir sağlayıcı gerekiyor.',
                "why": "429 Too Many Requests",
                "why_free_insufficient": "Tüm ücretsiz/yerel seçenekler denendi ve tükendi.",
            }],
        )

        report = build_ceo_report(mission)

        assert "KULLANICI ONAYI GEREKİYOR" in report
        assert "NEYE İHTİYAÇ VAR" in report
        assert "ÜCRETSİZ ALTERNATİFLER NEDEN YETMEDİ" in report
