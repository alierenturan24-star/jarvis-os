from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus
from src.mission.completion import evaluate_goal_completion, infer_completion_requirements
from src.mission.mission_engine import MissionEngine
from src.mission.models import Mission, MissionType
from src.strategy.execution_planner import build_self_check
from src.core.task_plan import TaskPlan
from src.mission.recovery import recover_mission


GOAL = ("Finance Engine'i PAPER modunda geliştir. Daha iyi stratejileri araştır; farklı "
        "stratejileri backtest ve out-of-sample veride karşılaştır. Overfitting yapma. "
        "Yeterli kanıt yoksa işlem açma.")

REAL_GOAL = ("Finance Engine, qualified strateji bulana kadar yeni güvenli strateji "
             "adayları araştır, farklı piyasa koşullarında backtest ve OOS testleri yap, "
             "uygun olanları PAPER'a geçir. Gerçek para kullanma. Yeterli kanıt yoksa "
             "işlem açma.")


def _mission(report=None):
    task = Task(title="finance", agent="finance", handler=lambda task: "ok", metadata={})
    task.status = TaskStatus.COMPLETED
    task.result = TaskResult(success=True, output="araştırıldı")
    if report is not None:
        task.metadata["report"] = report
    mission = Mission(title=GOAL, goal=GOAL, mission_type=MissionType.FINANCE,
                      departments=["finance", "research"], tasks=[task])
    mission.completion_requirements = infer_completion_requirements(GOAL, mission.departments)
    return mission


def test_department_success_is_not_finance_goal_success():
    mission = _mission()
    completion = evaluate_goal_completion(mission)
    check = build_self_check(mission, None)
    assert not completion.satisfied
    assert check.success_rate < 100
    assert "strategy comparison missing" in check.remaining
    assert "insufficient OOS evidence" in check.remaining
    assert "paper promotion not reached" in check.remaining


def test_evidence_backed_no_qualified_strategy_is_valid_completion():
    metric = {"trade_count": 4, "net_return_after_costs": -.01, "max_drawdown": .04,
              "win_rate": .25, "profit_factor": .8, "expectancy": -.002, "sharpe": -.2}
    candidates = [{"family": family, **metric, "train_metrics": metric,
                   "out_of_sample_metrics": metric, "qualified": False,
                   "qualification_reasons": ["OOS evidence below threshold"]}
                  for family in ("trend", "momentum")]
    mission = _mission({"strategy_lab": {"strategy_count": 2, "candidates": candidates,
                                          "decision": "NO QUALIFIED STRATEGY",
                                          "paper_promoted": False}})
    assert evaluate_goal_completion(mission).satisfied


def test_finance_trading_goal_resolves_capability_not_generic_ai():
    mission = MissionEngine().create_mission(GOAL)
    assert mission.target.category_hint == "trading bot"
    assert mission.target.category_hint != "ai agent"


def test_recovery_resumes_finance_from_missing_semantic_evidence():
    metric = {"trade_count": 4, "net_return_after_costs": -.01, "max_drawdown": .04,
              "win_rate": .25, "profit_factor": .8, "expectancy": -.002, "sharpe": -.2}
    candidates = [{"family": family, **metric, "train_metrics": metric,
                   "out_of_sample_metrics": metric, "qualified": False,
                   "qualification_reasons": ["OOS evidence below threshold"]}
                  for family in ("trend", "momentum")]
    calls = []
    mission = _mission()
    task = mission.tasks[0]
    def produce_evidence(current):
        calls.append("finance")
        current.metadata["report"] = {"strategy_lab": {"strategy_count": 2,
            "candidates": candidates, "decision": "NO QUALIFIED STRATEGY",
            "paper_promoted": False}}
        return "NO QUALIFIED STRATEGY"
    task.handler = produce_evidence
    plan = TaskPlan(GOAL)
    plan.add_task(task)

    report = recover_mission(mission, plan)
    assert calls == ["finance"]
    assert report.remaining_goals == []
    assert evaluate_goal_completion(mission).satisfied


def test_exact_real_goal_cannot_be_completed_as_research_only():
    mission = MissionEngine().create_mission(REAL_GOAL)
    assert mission.mission_type == MissionType.FINANCE
    assert "finance" in mission.departments
    assert mission.departments == ["finance"]
    assert {item.name for item in mission.completion_requirements} >= {
        "strategy_research", "strategy_comparison", "backtest", "oos",
        "risk_performance", "qualification", "paper_decision",
    }


def test_research_success_with_exact_goal_finance_evidence_missing_is_incomplete():
    task = Task(title="research", agent="research", handler=lambda task: "ok")
    task.status = TaskStatus.COMPLETED
    task.result = TaskResult(success=True, output="generic research report")
    mission = Mission(title=REAL_GOAL, goal=REAL_GOAL, departments=["research"], tasks=[task])
    mission.completion_requirements = infer_completion_requirements(REAL_GOAL, mission.departments)
    completion = evaluate_goal_completion(mission)
    check = build_self_check(mission, None)
    assert not completion.satisfied
    assert check.success_rate < 100
    assert check.remaining


def test_generic_ai_repository_is_not_finance_completion_evidence():
    mission = _mission({"top": [{"repo": "generic/ai-agent"}]})
    assert not evaluate_goal_completion(mission).satisfied


def test_qualified_candidate_allows_paper_promotion_but_never_live_money():
    metric = {"trade_count": 12, "net_return_after_costs": .02, "max_drawdown": .04,
              "win_rate": .55, "profit_factor": 1.2, "expectancy": .002, "sharpe": .7}
    candidates = [{"family": family, **metric, "train_metrics": metric,
                   "out_of_sample_metrics": metric, "qualified": True,
                   "qualification_reasons": []} for family in ("trend", "momentum")]
    mission = _mission({"strategy_lab": {"strategy_count": 2, "candidates": candidates,
        "decision": "PAPER CANDIDATE", "paper_promoted": True, "live_activation": False}})
    assert evaluate_goal_completion(mission).satisfied
    lab = mission.tasks[0].metadata["report"]["strategy_lab"]
    assert lab["paper_promoted"] is True
    assert lab["live_activation"] is False
