from datetime import datetime, timezone

from src.control_center.finance_engine import FinancePaperEngine, MarketBar
from src.control_center.store import ControlCenterStore


class MultiAssetMarket:
    prices = {"BTCUSDT": 50_000.0, "ETHUSDT": 3_000.0, "SOLUSDT": 150.0}

    @staticmethod
    def _symbol(asset):
        value = str(asset).upper()
        return value if value.endswith("USDT") else f"{value}USDT"

    def price(self, asset):
        symbol = self._symbol(asset)
        return {"symbol": symbol, "price": self.prices[symbol], "change_percent_24h": 1.2,
                "quote_volume_24h": 500_000_000, "source": "official fake"}

    def ohlcv(self, asset, interval="1h", limit=500):
        return fresh_bars(self.prices[self._symbol(asset)], limit)


def fresh_bars(start=100.0, count=500):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows = []
    for index in range(count):
        close = start * (1 + index * .0002)
        rows.append(MarketBar(now_ms - (count - 1 - index) * 3_600_000,
                              close, close * 1.005, close * .995, close, 10_000 + index))
    return rows


def dimensions(market):
    return {(symbol, timeframe): market.ohlcv(symbol, timeframe, 500)
            for symbol in market.prices for timeframe in ("1h", "4h")}


def test_autonomous_cycle_opens_only_reviewed_risk_capped_paper_positions(tmp_path, monkeypatch):
    market = MultiAssetMarket()
    engine = FinancePaperEngine(ControlCenterStore(tmp_path / "state.json"), market)
    monkeypatch.setattr(engine, "_candidate_qualification", lambda result: (True, [], 9.0))
    monkeypatch.setattr(engine, "_signal", lambda strategy_id, bars, index: True)

    result = engine.autonomous_paper_cycle(
        ["BTC", "ETH", "SOL"], ["1h", "4h"], bars_by_dimension=dimensions(market))

    assert result["status"] == "PAPER_POSITION_OPENED"
    assert result["safety"] == {"real_orders_sent": 0, "real_money_used": 0,
                                "live_trading_enabled": False, "broker_client_present": False}
    assert 1 <= result["portfolio_after"]["open_positions"] <= 3
    opened = [row for row in result["decisions"] if row.get("status") == "OPEN"]
    assert opened and all(row["review"]["status"] == "APPROVED_PAPER" for row in opened)
    assert all(row["risk_gate"]["approved"] for row in opened)
    assert result["portfolio_after"]["gross_exposure_percent"] <= .500001
    assert not hasattr(engine, "place_order")


def test_second_cycle_rejects_duplicate_assets_and_keeps_position_count_bounded(tmp_path, monkeypatch):
    market = MultiAssetMarket()
    engine = FinancePaperEngine(ControlCenterStore(tmp_path / "state.json"), market)
    monkeypatch.setattr(engine, "_candidate_qualification", lambda result: (True, [], 9.0))
    monkeypatch.setattr(engine, "_signal", lambda strategy_id, bars, index: True)
    evidence = dimensions(market)
    first = engine.autonomous_paper_cycle(bars_by_dimension=evidence)
    second = engine.autonomous_paper_cycle(bars_by_dimension=evidence)

    assert first["portfolio_after"]["open_positions"] <= 3
    assert second["portfolio_after"]["open_positions"] == first["portfolio_after"]["open_positions"]
    assert second["status"] == "NO_TRADE"
    assert any("zaten açık" in row.get("reason", "") for row in second["decisions"])


def test_cycle_fails_closed_when_one_market_dimension_is_missing(tmp_path):
    market = MultiAssetMarket()
    evidence = dimensions(market)
    evidence.pop(("SOLUSDT", "4h"))
    engine = FinancePaperEngine(ControlCenterStore(tmp_path / "state.json"), market)

    result = engine.autonomous_paper_cycle(bars_by_dimension=evidence)

    assert result["status"] == "NO_TRADE"
    assert result["portfolio_after"]["open_positions"] == 0
    assert result["safety"]["real_orders_sent"] == 0
