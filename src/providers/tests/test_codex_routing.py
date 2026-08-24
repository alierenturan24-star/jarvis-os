from __future__ import annotations

from src.jobs.job_manager import JobManager
from src.jobs.task import Task
from src.jobs.task_status import TaskStatus
from src.mission.models import Mission, MissionType
from src.mission.recovery import RecoveryAttemptHistory, RecoveryStep, recover_task
from src.providers.cost_optimizer import CostOptimizer
from src.providers.provider_manager import ProviderManager
from src.providers.provider_selector import ProviderSelector
from src.strategy.strategy_engine import AIStrategyEngine


class _FakeProvider:
    def __init__(self, available=True):
        self.available = available

    def is_available(self):
        return self.available


def _manager(**states):
    manager = ProviderManager()
    for name in manager.names():
        manager._providers[name] = _FakeProvider(states.get(name, False))
    return manager


def _recover(initial, states, success_provider=None):
    calls = []
    goal = "Repository bug'ını düzelt."

    def handler(task):
        provider = task.metadata.get("preferred_ai_provider")
        calls.append(provider)
        if provider == success_provider:
            return "Gerçek çözüm üretildi."
        return f"{provider} kullanım kotası aşıldı (limit aşıldı)."

    task = Task(title=goal, agent="research", handler=handler, metadata={"preferred_ai_provider": initial})
    task.status = TaskStatus.FAILED
    task.error = f"{initial} kullanım kotası aşıldı (limit aşıldı)."
    mission = Mission(title=goal, description=goal, mission_type=MissionType.CODE, goal=goal)
    attempts = recover_task(
        task, mission, provider_manager=_manager(**states), job_manager=JobManager(),
        history=RecoveryAttemptHistory(),
    )
    return task, mission, attempts, calls


class TestH_SimpleAndI_CodingRouting:
    def test_simple_youtube_task_never_selects_coding_worker(self):
        selected = ProviderSelector().select(
            "10 YouTube başlığı üret.", {"codex", "claude_code", "ollama"},
        )
        assert selected == "ollama"

    def test_coding_task_prefers_codex(self):
        manager = _manager(codex=True, claude_code=True, ollama=True)
        decision = CostOptimizer(manager).decide_for_message(
            "Repository kodunda bug debug et ve testleri düzelt."
        )
        assert decision.provider == "codex"
        assert decision.fallback == "claude_code"
        assert "API billing kullanılmaz" in decision.reason

        plan = AIStrategyEngine(cost_optimizer=CostOptimizer(manager)).plan(
            "Repository kodunda bug debug et ve testleri düzelt."
        )
        assert plan.ai_choice.provider == "codex"
        assert plan.free_sufficient is False
        assert plan.paid_required is False
        assert "mevcut cli aboneliği" in plan.paid_required_reason.casefold()


class TestJ_K_CrossWorkerFallbackAndGoal:
    def test_codex_quota_falls_back_to_claude(self):
        task, mission, attempts, calls = _recover(
            "codex", {"codex": True, "claude_code": True}, "claude_code",
        )
        assert task.status == TaskStatus.COMPLETED
        assert "claude_code" in calls
        assert mission.goal == "Repository bug'ını düzelt."
        assert any(a.succeeded for a in attempts)

    def test_claude_quota_falls_back_to_codex(self):
        task, mission, _, calls = _recover(
            "claude_code", {"codex": True, "claude_code": True}, "codex",
        )
        assert task.status == TaskStatus.COMPLETED
        assert "codex" in calls
        assert mission.goal == "Repository bug'ını düzelt."


class TestL_M_O_RecoveryBoundaries:
    def test_both_workers_fail_then_local_succeeds(self):
        task, _, _, calls = _recover(
            "codex", {"codex": True, "claude_code": True, "ollama": True}, "ollama",
        )
        assert task.status == TaskStatus.COMPLETED
        assert "claude_code" in calls and "ollama" in calls

    def test_only_paid_left_is_not_called(self):
        _, _, attempts, calls = _recover("codex", {"openai": True}, None)
        assert "openai" not in calls
        assert attempts[-1].step == RecoveryStep.PAID_APPROVAL_REQUIRED

    def test_no_ping_pong_repeats(self):
        _, _, attempts, calls = _recover(
            "codex", {"codex": True, "claude_code": True}, None,
        )
        assert calls.count("codex") <= 1
        assert calls.count("claude_code") <= 1
        assert len(attempts) <= 4
