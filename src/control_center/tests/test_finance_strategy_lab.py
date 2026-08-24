from src.control_center.finance_engine import FinancePaperEngine, MarketBar
from src.control_center.store import ControlCenterStore


def _bars(count=500):
    bars = []
    for index in range(count):
        cycle = index % 80
        close = 100 + (cycle if (index // 80) % 2 == 0 else 80 - cycle) * .8
        bars.append(MarketBar(index, close, close + 1, close - 1, close, 1000))
    return bars


def test_strategy_lab_compares_diverse_candidates_with_fair_oos_metrics(tmp_path):
    result = FinancePaperEngine(ControlCenterStore(tmp_path / "state.json")).strategy_lab("BTC", _bars())

    assert result["strategy_count"] >= 5
    assert len({candidate["family"] for candidate in result["candidates"]}) >= 5
    assert result["fees_rate"] > 0 and result["slippage_rate"] > 0
    for candidate in result["candidates"]:
        assert set(("train_metrics", "out_of_sample_metrics", "qualification_reasons", "selection_score")) <= candidate.keys()
        assert set(("trade_count", "net_return_after_costs", "max_drawdown", "win_rate",
                    "profit_factor", "expectancy", "sharpe")) <= candidate["out_of_sample_metrics"].keys()
    assert result["decision"] in {"PAPER CANDIDATE", "NO QUALIFIED STRATEGY"}
    assert result["live_activation"] is False


def test_no_qualified_strategy_blocks_paper_after_lab(tmp_path, monkeypatch):
    engine = FinancePaperEngine(ControlCenterStore(tmp_path / "state.json"))
    monkeypatch.setattr(engine, "_candidate_qualification", lambda result: (False, ["weak evidence"], -1.0))
    result = engine.strategy_lab("BTC", _bars())

    class Market:
        _symbol = staticmethod(lambda asset: "BTCUSDT")
        def price(self, asset):
            return {"symbol": "BTCUSDT", "price": 100.0, "change_percent_24h": 0, "source": "official fake"}
        def ohlcv(self, asset, interval="1h", limit=500):
            return _bars(max(100, limit))

    engine.market = Market()
    signal = engine.paper_signal("BTC")
    assert result["decision"] == "NO QUALIFIED STRATEGY"
    assert signal["status"] == "NO_TRADE"
    assert engine.store.snapshot()["paper"]["positions"] == []

