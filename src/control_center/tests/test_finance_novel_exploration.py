from src.control_center.finance_engine import FinancePaperEngine, MarketBar
from src.control_center.store import ControlCenterStore
from src.jobs.task import Task
from src.jobs.task_result import TaskResult
from src.jobs.task_status import TaskStatus
from src.mission.completion import evaluate_goal_completion, infer_completion_requirements
from src.mission.models import Mission
from src.mission.recovery import plan_needs_recovery
from src.mission.task_criticality import critical_failures
from src.core.task_plan import TaskPlan


GOAL = ("Finance Engine, mevcut 5 stratejiyi tekrarlamak yerine yeni strateji adaylari kesfet. "
        "Farkli asset ve piyasa regime'lerinde bounded exploration yap; her adayi backtest + OOS ile "
        "degerlendir. Qualified olan varsa PAPER'a gecir, yoksa NO QUALIFIED STRATEGY de. Gercek para kullanma.")


def _bars(count=500):
    rows = []
    price = 100.0
    for index in range(count):
        if index < 150:
            price *= 1.002
        elif index < 300:
            price *= 1 + (.035 if index % 2 else -.03)
        else:
            price *= 1 + (.001 if index % 20 < 10 else -.001)
        rows.append(MarketBar(index, price, price * 1.01, price * .99, price, 1000 + (index % 17) * 50))
    return rows


def _lab(tmp_path, monkeypatch=None):
    engine = FinancePaperEngine(ControlCenterStore(tmp_path / "state.json"))
    if monkeypatch is not None:
        monkeypatch.setattr(engine, "_candidate_qualification", lambda result: (False, ["bounded gate"], -1.0))
    bars = _bars()
    result = engine.explore_strategies(
        "BTC", bars_by_asset={"BTCUSDT": bars, "ETHUSDT": bars, "SOLUSDT": bars},
        candidate_budget=2, asset_budget=3,
    )
    return engine, result


def _mission(lab):
    task = Task(title="finance", agent="finance", metadata={"report": {"strategy_lab": lab}})
    task.status = TaskStatus.COMPLETED
    task.result = TaskResult(success=True, output="bounded exploration complete")
    mission = Mission(title=GOAL, goal=GOAL, departments=["finance"], tasks=[task])
    mission.completion_requirements = infer_completion_requirements(GOAL, mission.departments)
    return mission


def test_old_five_cannot_complete_new_strategy_goal(tmp_path):
    engine = FinancePaperEngine(ControlCenterStore(tmp_path / "state.json"))
    old = engine.strategy_lab("BTC", _bars())
    assert not evaluate_goal_completion(_mission(old)).satisfied


def test_novel_candidate_provenance_multi_asset_and_regime_complete(tmp_path):
    _, lab = _lab(tmp_path)
    required = {"name", "family", "source", "discovered_at", "baseline_or_new", "logic_summary",
                "parameters", "assets_tested", "regimes_tested"}
    novel = [row for row in lab["candidates"] if row["baseline_or_new"] == "new"]
    assert novel and all(required <= set(row) for row in novel)
    assert len(lab["assets_tested"]) == 3
    assert len(lab["regimes_tested"]) >= 2
    assert evaluate_goal_completion(_mission(lab)).satisfied


def test_one_asset_or_missing_regimes_cannot_close_requested_evidence(tmp_path):
    _, lab = _lab(tmp_path)
    lab["assets_tested"] = ["BTCUSDT"]
    assert not evaluate_goal_completion(_mission(lab)).satisfied
    _, lab = _lab(tmp_path / "second")
    lab["regimes_tested"] = []
    assert not evaluate_goal_completion(_mission(lab)).satisfied


def test_exploration_budget_is_hard_bounded(tmp_path):
    _, lab = _lab(tmp_path)
    assert lab["bounded"] is True
    assert lab["novel_strategy_count"] == 2
    assert lab["exploration_budget"] == {"candidate_budget": 2, "asset_budget": 3,
                                         "candidate_runs": 7, "asset_runs": 3}


def test_qualified_promotes_only_to_paper(tmp_path, monkeypatch):
    engine = FinancePaperEngine(ControlCenterStore(tmp_path / "state.json"))
    monkeypatch.setattr(engine, "_candidate_qualification", lambda result: (True, [], 1.0))
    bars = _bars()
    lab = engine.explore_strategies("BTC", bars_by_asset={"BTCUSDT": bars, "ETHUSDT": bars})
    assert lab["paper_promoted"] is True and lab["decision"] == "PAPER CANDIDATE"
    assert lab["live_activation"] is False


def test_no_qualified_is_no_trade_and_no_real_money(tmp_path, monkeypatch):
    engine, lab = _lab(tmp_path, monkeypatch)
    assert lab["bounded_exploration_outcome"] == "NO QUALIFIED STRATEGY AFTER BOUNDED EXPLORATION"
    assert lab["paper_promoted"] is False and lab["live_activation"] is False
    assert not hasattr(engine, "place_order")


def test_supporting_timeout_does_not_block_complete_goal_but_critical_does(tmp_path):
    _, lab = _lab(tmp_path)
    mission = _mission(lab)
    supporting = Task(title="evaluation support", agent="evaluation", metadata={"goal_critical": False})
    supporting.status = TaskStatus.FAILED
    supporting.error = "timeout after 75 seconds"
    supporting.result = TaskResult(success=False, error=supporting.error)
    mission.tasks.append(supporting)
    plan = TaskPlan(GOAL)
    for task in mission.tasks:
        plan.add_task(task)
    assert evaluate_goal_completion(mission).satisfied
    assert not critical_failures(plan)
    assert not plan_needs_recovery(plan, mission)

    supporting.metadata["goal_critical"] = True
    assert critical_failures(plan) == [supporting]
    assert plan_needs_recovery(plan, mission)

