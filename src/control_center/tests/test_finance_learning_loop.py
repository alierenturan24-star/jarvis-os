from src.control_center.finance_engine import FinancePaperEngine, MarketBar
from src.control_center.store import ControlCenterStore
from src.finance.learning import FinanceLearningAgent
from src.jobs.task import Task
from src.mission.department_adapters import DepartmentAdapterRegistry


def _bars(count=240):
    price = 100.0
    result = []
    for index in range(count):
        price *= 1.003 if index < 80 else (1.02 if index % 2 else .98) if index < 160 else 1.0002
        result.append(MarketBar(index, price, price * 1.01, price * .99, price, 1000 + index % 20))
    return result


def _dimensions():
    bars = _bars()
    return {(asset, timeframe): bars for asset in ("BTCUSDT", "ETHUSDT")
            for timeframe in ("1h", "4h")}


def test_learning_handler_is_connected():
    assert DepartmentAdapterRegistry().resolve("learning") is not None


def test_restart_loads_history_and_second_mission_changes_candidates(tmp_path):
    path = tmp_path / "state.json"
    first = FinancePaperEngine(ControlCenterStore(path)).explore_strategies(
        "BTC", bars_by_dimension=_dimensions(), candidate_budget=3)
    first_ids = {row["candidate_id"] for row in first["candidates"] if row["baseline_or_new"] == "new"}
    restarted = FinancePaperEngine(ControlCenterStore(path))
    second = restarted.explore_strategies("BTC", bars_by_dimension=_dimensions(), candidate_budget=3)
    second_ids = {row["candidate_id"] for row in second["candidates"] if row["baseline_or_new"] == "new"}
    assert first_ids and second_ids and first_ids.isdisjoint(second_ids)
    assert not [row for row in second["candidates"] if row["baseline_or_new"] == "baseline"]
    persisted = ControlCenterStore(path).snapshot()["finance_exploration"]
    assert first_ids | second_ids == set(persisted["candidates"])
    assert all(row["rejection_reasons"] == row["qualification_reasons"] for row in persisted["candidates"].values())


def test_justified_retest_is_recorded_and_learning_persists(tmp_path):
    store = ControlCenterStore(tmp_path / "state.json")
    engine = FinancePaperEngine(store)
    engine.explore_strategies("BTC", bars_by_dimension=_dimensions(), candidate_budget=3)
    engine.explore_strategies("BTC", bars_by_dimension=_dimensions(), candidate_budget=3)
    retest = engine.explore_strategies("BTC", bars_by_dimension=_dimensions(), candidate_budget=1,
                                       retest_reason="validation/retest on a new data window")
    row = next(item for item in retest["candidates"] if item["baseline_or_new"] == "new")
    assert row["test_count"] == 2 and row["retest_reason"].startswith("validation")
    task = Task(title="learn", agent="learning")
    FinanceLearningAgent(store).execute(task)
    assert task.metadata["report"]["learning_persisted"] is True
    assert store.snapshot()["finance_exploration"]["last_learning"]["can_qualify"] is False


def test_real_evidence_dimensions_and_no_live_money(tmp_path):
    lab = FinancePaperEngine(ControlCenterStore(tmp_path / "state.json")).explore_strategies(
        "BTC", bars_by_dimension=_dimensions(), candidate_budget=2)
    assert set(lab["assets_tested"]) == {"BTCUSDT", "ETHUSDT"}
    assert set(lab["timeframes_tested"]) == {"1h", "4h"}
    assert len(lab["regimes_tested"]) >= 2
    assert lab["live_activation"] is False
