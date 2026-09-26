from __future__ import annotations

import json
import hashlib
import math
import statistics
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.control_center.store import ControlCenterStore, utc_now
from src.security.action_policy import ActionPolicy


@dataclass(frozen=True)
class MarketBar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class BinancePublicMarketData:
    """Credential-free, read-only adapters for official Binance public APIs."""

    SPOT = "https://api.binance.com/api/v3"
    FUTURES = "https://fapi.binance.com/fapi/v1"
    SOURCE = "Binance official public API"

    @staticmethod
    def _symbol(asset: str) -> str:
        compact = "".join(c for c in asset.upper() if c.isalnum())
        if not compact:
            raise ValueError("Varlık sembolü boş olamaz.")
        if any(compact.endswith(q) and len(compact) > len(q) for q in ("USDT", "USDC", "EUR", "BTC")):
            return compact
        return f"{compact}USDT"

    def _get(self, base: str, endpoint: str, params: dict[str, Any]) -> Any:
        url = f"{base}/{endpoint}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": "JARVIS-Control-Center/1.0"})
        with urllib.request.urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))

    def price(self, asset: str) -> dict[str, Any]:
        symbol = self._symbol(asset)
        row = self._get(self.SPOT, "ticker/24hr", {"symbol": symbol})
        return {"source": self.SOURCE, "symbol": symbol, "price": float(row["lastPrice"]),
                "change_percent_24h": float(row["priceChangePercent"]), "volume_24h": float(row["volume"]),
                "quote_volume_24h": float(row["quoteVolume"]), "high_24h": float(row["highPrice"]),
                "low_24h": float(row["lowPrice"]), "trade_count_24h": int(row["count"]), "observed_at": utc_now()}

    def ohlcv(self, asset: str, interval: str = "1h", limit: int = 500) -> list[MarketBar]:
        rows = self._get(self.SPOT, "klines", {"symbol": self._symbol(asset), "interval": interval,
                                                "limit": max(50, min(limit, 1000))})
        return [MarketBar(int(r[0]), *map(float, (r[1], r[2], r[3], r[4], r[5]))) for r in rows]

    def intelligence(self, asset: str, depth: int = 10, trades: int = 20) -> dict[str, Any]:
        """Broad market snapshot. Derivatives fields fail independently for spot-only symbols."""
        symbol = self._symbol(asset)
        ticker = self.price(symbol)
        book = self._get(self.SPOT, "depth", {"symbol": symbol, "limit": min(max(depth, 5), 100)})
        recent = self._get(self.SPOT, "trades", {"symbol": symbol, "limit": min(max(trades, 1), 100)})
        exchange = self._get(self.SPOT, "exchangeInfo", {"symbol": symbol})["symbols"][0]
        bars = self.ohlcv(symbol, "1h", 50)
        returns = [(bars[i].close / bars[i - 1].close) - 1 for i in range(1, len(bars))]
        result = {**ticker, "volatility_1h_annualized": statistics.pstdev(returns) * math.sqrt(24 * 365),
                  "order_book": {"last_update_id": book["lastUpdateId"],
                                 "bids": [[float(p), float(q)] for p, q in book["bids"]],
                                 "asks": [[float(p), float(q)] for p, q in book["asks"]]},
                  "recent_trades": [{"price": float(x["price"]), "quantity": float(x["qty"]),
                                     "timestamp": int(x["time"]), "buyer_was_maker": bool(x["isBuyerMaker"])} for x in recent],
                  "market_metadata": {"status": exchange["status"], "base_asset": exchange["baseAsset"],
                                      "quote_asset": exchange["quoteAsset"], "order_types": exchange["orderTypes"],
                                      "spot_trading_allowed": bool(exchange.get("isSpotTradingAllowed"))},
                  "derivatives": None, "capabilities": ["price", "ohlcv", "volume", "volatility", "order_book", "recent_trades", "market_metadata"]}
        try:
            premium = self._get(self.FUTURES, "premiumIndex", {"symbol": symbol})
            interest = self._get(self.FUTURES, "openInterest", {"symbol": symbol})
            result["derivatives"] = {"funding_rate": float(premium["lastFundingRate"]),
                                     "next_funding_time": int(premium["nextFundingTime"]),
                                     "mark_price": float(premium["markPrice"]), "open_interest": float(interest["openInterest"])}
            result["capabilities"] += ["funding_rate", "open_interest"]
        except (OSError, ValueError, KeyError):
            pass
        return result


def _metrics(trades: list[dict[str, Any]], starting_equity: float = 1.0) -> dict[str, Any]:
    returns = [float(x.get("pnl_percent", x.get("return", 0))) for x in trades]
    pnls = [float(x.get("pnl", r * starting_equity)) for x, r in zip(trades, returns)]
    wins, losses = [x for x in pnls if x > 0], [x for x in pnls if x <= 0]
    equity, peak, max_dd, loss_streak, max_loss_streak = starting_equity, starting_equity, 0.0, 0, 0
    for pnl in pnls:
        equity += pnl; peak = max(peak, equity); max_dd = max(max_dd, (peak - equity) / peak if peak else 0)
        loss_streak = loss_streak + 1 if pnl <= 0 else 0; max_loss_streak = max(max_loss_streak, loss_streak)
    sharpe = None
    if len(returns) > 1 and statistics.stdev(returns) > 0:
        sharpe = statistics.mean(returns) / statistics.stdev(returns) * math.sqrt(len(returns))
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    avg_win = statistics.mean(wins) if wins else 0.0; avg_loss = statistics.mean(losses) if losses else 0.0
    return {"trade_count": len(trades), "return": (equity - starting_equity) / starting_equity if starting_equity else 0,
            "net_return_after_costs": (equity - starting_equity) / starting_equity if starting_equity else 0,
            "max_drawdown": max_dd, "win_rate": len(wins) / len(trades) if trades else None,
            "loss_rate": len(losses) / len(trades) if trades else None,
            "profit_factor": gross_profit / gross_loss if gross_loss else None,
            "expectancy": statistics.mean(pnls) if pnls else None, "sharpe": sharpe,
            "average_win": avg_win, "average_loss": avg_loss, "largest_loss": min(losses) if losses else 0.0,
            "consecutive_losses": max_loss_streak,
            "realized_risk_reward": avg_win / abs(avg_loss) if losses and avg_loss else None}


class FinancePaperEngine:
    """Backtest and paper lifecycle only. This class contains no order execution client."""

    FEE_RATE = .001
    SLIPPAGE_RATE = .0005
    STOP_RATE = .02
    TARGET_RATE = .04
    DEFAULT_RISK_FRACTION = .005
    MAX_RISK_FRACTION = .01
    MAX_POSITION_NOTIONAL_FRACTION = .20
    MAX_GROSS_EXPOSURE_FRACTION = .50
    MAX_OPEN_POSITIONS = 3

    def __init__(self, store: ControlCenterStore, market: BinancePublicMarketData | None = None) -> None:
        self.store, self.market, self.policy = store, market or BinancePublicMarketData(), ActionPolicy()

    def backtest(self, asset: str, bars: list[MarketBar] | None = None) -> dict[str, Any]:
        bars = bars or self.market.ohlcv(asset)
        if len(bars) < 80:
            raise ValueError("Backtest için en az 80 gerçek OHLCV bar gerekli.")
        split = int(len(bars) * .7)
        run = self._run_candidate(self.STRATEGIES[0], bars, split)
        trades = run.pop("_trades")
        train, oos = [x for x in trades if not x["out_of_sample"]], [x for x in trades if x["out_of_sample"]]
        result = {"id": f"bt-{uuid.uuid4().hex}", "asset": self.market._symbol(asset), "source": "Binance official OHLCV",
                  "strategy": "SMA 10/50 crossover", "regime": self._regime(bars), "sample_bars": len(bars),
                  "train_bars": split, "out_of_sample_bars": len(bars)-split, "fees_rate": self.FEE_RATE,
                  "slippage_rate": self.SLIPPAGE_RATE, "stop_rate": self.STOP_RATE,
                  "target_rate": self.TARGET_RATE, **_metrics(trades), "trades": len(trades),
                  "train_metrics": _metrics(train), "out_of_sample_metrics": _metrics(oos), "qualified": False,
                  "label": "BACKTEST — NOT LIVE", "created_at": utc_now()}
        self.store.append("backtests", result)
        return result

    STRATEGIES: tuple[dict[str, Any], ...] = (
        {"id": "sma_trend", "name": "SMA 10/50 crossover", "family": "trend", "warmup": 50},
        {"id": "ema_momentum", "name": "EMA 12/26 momentum", "family": "momentum", "warmup": 27},
        {"id": "rsi_reversion", "name": "RSI(14) mean reversion", "family": "mean_reversion", "warmup": 15},
        {"id": "donchian_breakout", "name": "Donchian 20 breakout", "family": "breakout", "warmup": 21},
        {"id": "regime_trend", "name": "Volatility-filtered trend", "family": "regime_aware", "warmup": 50},
    )

    NOVEL_STRATEGIES: tuple[dict[str, Any], ...] = (
        {"id": "rsi_trend_pullback", "name": "RSI trend pullback", "family": "trend_pullback", "warmup": 50,
         "parameters": {"trend_sma": 50, "rsi_period": 14, "rsi_entry": 45},
         "logic_summary": "Long-trend filter combined with an RSI pullback entry.",
         "source": "local capability combination: SMA + RSI"},
        {"id": "donchian_volume_breakout", "name": "Volume-confirmed Donchian breakout", "family": "volume_breakout", "warmup": 30,
         "parameters": {"lookback": 20, "volume_lookback": 20, "volume_multiplier": 1.1},
         "logic_summary": "A price breakout must also have above-average volume.",
         "source": "local capability combination: Donchian + volume"},
        {"id": "low_vol_ema_momentum", "name": "Low-volatility EMA momentum", "family": "volatility_momentum", "warmup": 40,
         "parameters": {"fast": 8, "slow": 21, "volatility_lookback": 20, "max_volatility": .018},
         "logic_summary": "Fast EMA momentum is active only below a realized-volatility bound.",
         "source": "local capability combination: EMA + realized volatility"},
        {"id": "rsi_trend_pullback_v2", "name": "RSI trend pullback (strict)", "family": "trend_pullback", "warmup": 80,
         "parameters": {"trend_sma": 80, "rsi_period": 14, "rsi_entry": 40},
         "logic_summary": "A stricter RSI pullback variation with a longer trend filter.",
         "source": "history-guided parameter variation: SMA + RSI"},
        {"id": "donchian_volume_breakout_v2", "name": "Volume-confirmed Donchian breakout (30)", "family": "volume_breakout", "warmup": 35,
         "parameters": {"lookback": 30, "volume_lookback": 20, "volume_multiplier": 1.2},
         "logic_summary": "A longer breakout window and stronger volume confirmation.",
         "source": "history-guided parameter variation: Donchian + volume"},
        {"id": "low_vol_ema_momentum_v2", "name": "Low-volatility EMA momentum (13/34)", "family": "volatility_momentum", "warmup": 50,
         "parameters": {"fast": 13, "slow": 34, "volatility_lookback": 20, "max_volatility": .014},
         "logic_summary": "A slower EMA variation with a tighter volatility bound.",
         "source": "history-guided parameter variation: EMA + realized volatility"},
    )

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        alpha, value = 2 / (period + 1), values[0]
        for item in values[1:]:
            value = alpha * item + (1 - alpha) * value
        return value

    @staticmethod
    def _rsi(values: list[float], period: int = 14) -> float:
        changes = [values[i] - values[i - 1] for i in range(1, len(values))][-period:]
        gains = sum(max(x, 0) for x in changes) / period
        losses = sum(max(-x, 0) for x in changes) / period
        return 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)

    def _signal(self, strategy_id: str, bars: list[MarketBar], index: int) -> bool:
        """Signal uses bars strictly before ``index``; execution is at index close."""
        closes = [bar.close for bar in bars]
        history = closes[:index]
        if strategy_id == "sma_trend":
            return sum(history[-10:]) / 10 > sum(history[-50:]) / 50
        if strategy_id == "ema_momentum":
            return self._ema(history[-60:], 12) > self._ema(history[-60:], 26)
        if strategy_id == "rsi_reversion":
            return self._rsi(history[-15:]) < 30
        if strategy_id == "donchian_breakout":
            return history[-1] >= max(history[-20:])
        if strategy_id == "rsi_trend_pullback":
            return history[-1] > sum(history[-50:]) / 50 and self._rsi(history[-15:]) < 45
        if strategy_id == "donchian_volume_breakout":
            volumes = [bar.volume for bar in bars[:index]]
            return history[-1] >= max(history[-20:]) and volumes[-1] > statistics.mean(volumes[-20:]) * 1.1
        if strategy_id == "low_vol_ema_momentum":
            recent = [history[i] / history[i - 1] - 1 for i in range(len(history) - 20, len(history))]
            return statistics.pstdev(recent) <= .018 and self._ema(history[-40:], 8) > self._ema(history[-40:], 21)
        if strategy_id == "rsi_trend_pullback_v2":
            return history[-1] > sum(history[-80:]) / 80 and self._rsi(history[-15:]) < 40
        if strategy_id == "donchian_volume_breakout_v2":
            volumes = [bar.volume for bar in bars[:index]]
            return history[-1] >= max(history[-30:]) and volumes[-1] > statistics.mean(volumes[-20:]) * 1.2
        if strategy_id == "low_vol_ema_momentum_v2":
            recent = [history[i] / history[i - 1] - 1 for i in range(len(history) - 20, len(history))]
            return statistics.pstdev(recent) <= .014 and self._ema(history[-50:], 13) > self._ema(history[-50:], 34)
        returns = [history[i] / history[i - 1] - 1 for i in range(max(1, len(history) - 20), len(history))]
        volatility = statistics.pstdev(returns) if len(returns) > 1 else 0
        return volatility <= .025 and sum(history[-10:]) / 10 > sum(history[-50:]) / 50

    def _run_candidate(self, candidate: dict[str, Any], bars: list[MarketBar], split: int) -> dict[str, Any]:
        trades: list[dict[str, Any]] = []
        position: tuple[float, int] | None = None
        warmup = int(candidate["warmup"])
        for index in range(warmup, len(bars)):
            active = self._signal(candidate["id"], bars, index)
            if position is None and active:
                position = (bars[index].close * (1 + self.SLIPPAGE_RATE), index)
                continue
            elif position is not None:
                entry, opened = position
                stop, target = entry * (1 - self.STOP_RATE), entry * (1 + self.TARGET_RATE)
                # If a candle touches both levels, use the adverse result. This
                # is deliberately conservative because intrabar order is unknown.
                if bars[index].low <= stop:
                    raw_exit, exit_reason = stop, "STOP"
                elif bars[index].high >= target:
                    raw_exit, exit_reason = target, "TARGET"
                elif not active:
                    raw_exit, exit_reason = bars[index].close, "SIGNAL_EXIT"
                else:
                    continue
                exit_price = raw_exit * (1 - self.SLIPPAGE_RATE)
                net = exit_price / entry - 1 - 2 * self.FEE_RATE
                trades.append({"entry_index": opened, "exit_index": index, "return": net,
                               "pnl_percent": net, "pnl": net, "out_of_sample": opened >= split,
                               "regime": self._regime_at(bars, opened), "exit_reason": exit_reason})
                position = None
        if position is not None:
            entry, opened = position
            exit_price = bars[-1].close * (1 - self.SLIPPAGE_RATE)
            net = exit_price / entry - 1 - 2 * self.FEE_RATE
            trades.append({"entry_index": opened, "exit_index": len(bars) - 1, "return": net,
                           "pnl_percent": net, "pnl": net, "out_of_sample": opened >= split,
                           "regime": self._regime_at(bars, opened), "exit_reason": "END_OF_SAMPLE"})
        train = [trade for trade in trades if not trade["out_of_sample"]]
        oos = [trade for trade in trades if trade["out_of_sample"]]
        regimes = sorted({self._regime_at(bars, i) for i in range(max(50, warmup), len(bars))})
        return {**candidate, **_metrics(trades), "trades": len(trades), "_trades": trades,
                "train_metrics": _metrics(train), "out_of_sample_metrics": _metrics(oos),
                "regimes_tested": regimes,
                "regime_metrics": {name: _metrics([t for t in trades if t["regime"] == name]) for name in regimes}}

    @staticmethod
    def _candidate_qualification(result: dict[str, Any]) -> tuple[bool, list[str], float]:
        overall, oos = result, result["out_of_sample_metrics"]
        reasons: list[str] = []
        if overall["trade_count"] < 8: reasons.append("insufficient trade count (<8)")
        if oos["trade_count"] < 3: reasons.append("insufficient OOS trades (<3)")
        if oos["net_return_after_costs"] <= 0: reasons.append("OOS net return is not positive")
        if overall["max_drawdown"] > .20: reasons.append("max drawdown exceeds 20%")
        if (oos["profit_factor"] or 0) < 1.05: reasons.append("OOS profit factor below 1.05")
        if (oos["sharpe"] or 0) <= 0: reasons.append("OOS risk-adjusted performance is not positive")
        score = (oos["net_return_after_costs"] * 100 - overall["max_drawdown"] * 60
                 + min(oos["profit_factor"] or 0, 3) * 4 + min(oos["sharpe"] or 0, 3) * 3
                 + min(overall["trade_count"], 30) / 10)
        return not reasons, reasons, round(score, 4)

    def strategy_lab(self, asset: str, bars: list[MarketBar] | None = None) -> dict[str, Any]:
        """Compare diverse candidates fairly and fail closed when evidence is weak."""
        bars = bars or self.market.ohlcv(asset)
        if len(bars) < 120:
            raise ValueError("Strategy Lab için en az 120 gerçek OHLCV bar gerekli.")
        split = int(len(bars) * .7)
        candidates = []
        for definition in self.STRATEGIES:
            result = self._run_candidate(definition, bars, split)
            qualified, reasons, score = self._candidate_qualification(result)
            result.update(qualified=qualified, qualification_reasons=reasons, selection_score=score)
            candidates.append(result)
        qualified = sorted((item for item in candidates if item["qualified"]), key=lambda x: x["selection_score"], reverse=True)
        best = qualified[0] if qualified else None
        comparison = {
            "id": f"lab-{uuid.uuid4().hex}", "asset": self.market._symbol(asset),
            "source": "Binance official OHLCV", "market_truth_source": True,
            "sample_bars": len(bars), "train_bars": split, "out_of_sample_bars": len(bars) - split,
            "fees_rate": self.FEE_RATE, "slippage_rate": self.SLIPPAGE_RATE,
            "candidates": candidates, "strategy_count": len(candidates),
            "best_candidate": best["name"] if best else None,
            "decision": "PAPER CANDIDATE" if best else "NO QUALIFIED STRATEGY",
            "paper_promoted": bool(best), "live_activation": False,
            "label": "STRATEGY LAB — BACKTEST/OOS — NOT LIVE", "created_at": utc_now(),
        }
        def persist(state: dict[str, Any]) -> None:
            state.setdefault("strategy_labs", []).append(comparison)
            state["engines"]["finance"].update(
                mode="PAPER" if best else "RESEARCH",
                paper_candidate=best["id"] if best else None,
                paper_candidate_name=best["name"] if best else None,
                strategy_lab_decision=comparison["decision"], live_activation=False,
            )
        self.store.update(persist)
        return comparison

    def explore_strategies(self, asset: str, *, asset_budget: int = 3, candidate_budget: int = 3,
                           timeframe_budget: int = 2,
                           bars_by_asset: dict[str, list[MarketBar]] | None = None,
                           bars_by_dimension: dict[tuple[str, str], list[MarketBar]] | None = None,
                           retest_reason: str | None = None) -> dict[str, Any]:
        """Explore novel local candidates with explicit finite budgets.

        Baselines are retained for comparison but never counted as novel.
        All candidate/asset runs share fees, slippage and the 70/30 split.
        """
        requested = self.market._symbol(asset)
        asset_budget = max(1, min(int(asset_budget), 5))
        candidate_budget = max(1, min(int(candidate_budget), len(self.NOVEL_STRATEGIES)))
        timeframe_budget = max(1, min(int(timeframe_budget), 3))
        if bars_by_dimension is None and bars_by_asset is None:
            symbols = list(dict.fromkeys((requested, "ETHUSDT", "SOLUSDT")))[:asset_budget]
            timeframes = ("1h", "4h")[:timeframe_budget]
            bars_by_dimension = {(symbol, timeframe): self.market.ohlcv(symbol, timeframe)
                                 for symbol in symbols for timeframe in timeframes}
        elif bars_by_dimension is None:
            bars_by_asset = dict(list(bars_by_asset.items())[:asset_budget])
            bars_by_dimension = {(symbol, "1h"): series for symbol, series in bars_by_asset.items()}
        bars_by_dimension = dict(bars_by_dimension or {})
        if not bars_by_dimension or any(len(series) < 120 for series in bars_by_dimension.values()):
            raise ValueError("Bounded exploration requires at least 120 OHLCV bars per asset.")

        history = self.store.snapshot().get("finance_exploration", {}).get("candidates", {})
        untested = [item for item in self.NOVEL_STRATEGIES if item["id"] not in history]
        selected = untested[:candidate_budget]
        if not selected and retest_reason:
            selected = list(self.NOVEL_STRATEGIES[:candidate_budget])
        if not selected:
            # Exhausted finite catalogue: vary the evidence dimension, never
            # relabel an old candidate as newly discovered.
            selected = []

        discovered_at = datetime.now(timezone.utc).isoformat()
        definitions = [
            {**item, "baseline_or_new": "baseline", "source": "JARVIS built-in Strategy Lab baseline",
             "discovered_at": "built-in baseline", "logic_summary": item["name"], "parameters": {}}
            for item in self.STRATEGIES
        ] + [
            {**item, "baseline_or_new": "new", "discovered_at": discovered_at}
            for item in selected
        ]
        # Baselines are reference controls on the first run only.
        if history:
            definitions = [item for item in definitions if item["baseline_or_new"] == "new"]
        candidates: list[dict[str, Any]] = []
        for definition in definitions:
            trades: list[dict[str, Any]] = []
            asset_results: list[dict[str, Any]] = []
            for (symbol, timeframe), series in bars_by_dimension.items():
                split = int(len(series) * .7)
                run = self._run_candidate(definition, series, split)
                run_trades = run.pop("_trades")
                trades.extend({**trade, "asset": symbol, "timeframe": timeframe} for trade in run_trades)
                asset_results.append({"asset": symbol, "timeframe": timeframe, "sample_bars": len(series), "train_bars": split,
                                      "out_of_sample_bars": len(series) - split,
                                      "train_metrics": run["train_metrics"],
                                      "out_of_sample_metrics": run["out_of_sample_metrics"],
                                      "regime_metrics": run["regime_metrics"]})
            train = [trade for trade in trades if not trade["out_of_sample"]]
            oos = [trade for trade in trades if trade["out_of_sample"]]
            regimes = sorted({name for row in asset_results for name in row["regime_metrics"]})
            result = {**definition, **_metrics(trades), "trades": len(trades),
                      "train_metrics": _metrics(train), "out_of_sample_metrics": _metrics(oos),
                      "candidate_id": definition["id"],
                      "assets_tested": sorted({key[0] for key in bars_by_dimension}),
                      "timeframes_tested": sorted({key[1] for key in bars_by_dimension}), "asset_results": asset_results,
                      "regimes_tested": regimes,
                      "regime_metrics": {name: _metrics([t for t in trades if t["regime"] == name]) for name in regimes}}
            result["test_combinations"] = [{"asset": symbol, "timeframe": timeframe,
                "data_window": [series[0].timestamp, series[-1].timestamp],
                "parameters": definition.get("parameters", {}), "regimes": sorted(run["regime_metrics"])}
                for (symbol, timeframe), series in bars_by_dimension.items()
                for run in [next(item for item in asset_results
                                 if item["asset"] == symbol and item["timeframe"] == timeframe)]]
            qualified, reasons, score = self._candidate_qualification(result)
            result.update(qualified=qualified, qualification_reasons=reasons, rejection_reasons=reasons,
                          qualification_result="QUALIFIED" if qualified else "REJECTED",
                          paper_status="PAPER_CANDIDATE" if qualified else "NO_TRADE", selection_score=score)
            candidates.append(result)

        # Baselines are comparison controls, not promotion candidates for a
        # goal that explicitly asked for newly discovered strategies.
        qualified = sorted((row for row in candidates if row["qualified"] and row["baseline_or_new"] == "new"),
                           key=lambda row: row["selection_score"], reverse=True)
        best = qualified[0] if qualified else None
        comparison = {
            "id": f"lab-{uuid.uuid4().hex}", "asset": requested,
            "source": "Binance official OHLCV", "market_truth_source": True,
            "assets_tested": sorted({key[0] for key in bars_by_dimension}),
            "asset_count": len({key[0] for key in bars_by_dimension}),
            "timeframes_tested": sorted({key[1] for key in bars_by_dimension}),
            "regimes_tested": sorted({name for row in candidates for name in row["regimes_tested"]}),
            "fees_rate": self.FEE_RATE, "slippage_rate": self.SLIPPAGE_RATE,
            "candidates": candidates, "strategy_count": len(candidates),
            "novel_strategy_count": sum(row["baseline_or_new"] == "new" for row in candidates),
            "exploration_budget": {"candidate_budget": candidate_budget, "asset_budget": asset_budget,
                                   "candidate_runs": len(definitions), "asset_runs": len(bars_by_dimension)},
            "bounded": True, "best_candidate": best["name"] if best else None,
            "decision": "PAPER CANDIDATE" if best else "NO QUALIFIED STRATEGY",
            "bounded_exploration_outcome": "QUALIFIED STRATEGY" if best else "NO QUALIFIED STRATEGY AFTER BOUNDED EXPLORATION",
            "paper_promoted": bool(best), "live_activation": False,
            "label": "BOUNDED STRATEGY EXPLORATION - BACKTEST/OOS - NOT LIVE", "created_at": utc_now(),
        }
        def persist(state: dict[str, Any]) -> None:
            state.setdefault("strategy_labs", []).append(comparison)
            state["engines"]["finance"].update(
                mode="PAPER" if best else "RESEARCH", paper_candidate=best["id"] if best else None,
                paper_candidate_name=best["name"] if best else None,
                strategy_lab_decision=comparison["decision"], live_activation=False,
            )
            exploration = state.setdefault("finance_exploration", {"candidates": {}, "runs": []})
            records = exploration.setdefault("candidates", {})
            for row in candidates:
                if row["baseline_or_new"] != "new":
                    continue
                previous = records.get(row["candidate_id"], {})
                row["first_tested_at"] = previous.get("first_tested_at", discovered_at)
                row["last_tested_at"] = discovered_at
                row["test_count"] = int(previous.get("test_count", 0)) + 1
                row["retest_reason"] = retest_reason
                if previous.get("test_combinations") and retest_reason:
                    row["test_combinations"] = previous["test_combinations"] + row["test_combinations"]
                records[row["candidate_id"]] = {key: value for key, value in row.items() if key != "_trades"}
            exploration.setdefault("runs", []).append({"id": comparison["id"], "created_at": discovered_at,
                "candidate_ids": [row["candidate_id"] for row in candidates if row["baseline_or_new"] == "new"],
                "assets": comparison["assets_tested"], "timeframes": comparison["timeframes_tested"]})
        self.store.update(persist)
        return comparison

    @staticmethod
    def _regime(bars: list[MarketBar]) -> str:
        closes = [b.close for b in bars[-50:]]
        change = closes[-1] / closes[0] - 1
        volatility = statistics.pstdev([(closes[i] / closes[i-1]) - 1 for i in range(1, len(closes))])
        return ("HIGH_VOLATILITY" if volatility > .02 else "TREND_UP" if change > .05 else
                "TREND_DOWN" if change < -.05 else "RANGE")

    @staticmethod
    def _regime_at(bars: list[MarketBar], index: int) -> str:
        window = bars[max(0, index - 50):index + 1]
        if len(window) < 10:
            return "UNKNOWN"
        closes = [bar.close for bar in window]
        returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        volatility = statistics.pstdev(returns) if len(returns) > 1 else 0
        change = closes[-1] / closes[0] - 1
        if volatility > .02:
            return "HIGH_VOLATILITY"
        if volatility < .004:
            return "LOW_VOLATILITY"
        if change > .05:
            return "TREND_UP"
        if change < -.05:
            return "TREND_DOWN"
        return "RANGE"

    @classmethod
    def _all_strategies(cls) -> tuple[dict[str, Any], ...]:
        return cls.STRATEGIES + cls.NOVEL_STRATEGIES

    def _candidate_record(self, strategy_id: str) -> dict[str, Any] | None:
        state = self.store.snapshot()
        learned = state.get("finance_exploration", {}).get("candidates", {}).get(strategy_id)
        if isinstance(learned, dict):
            return learned
        for lab in reversed(state.get("strategy_labs", [])):
            for candidate in lab.get("candidates", []):
                if candidate.get("id") == strategy_id:
                    return candidate
        return None

    @staticmethod
    def _evidence_fingerprint(symbol: str, timeframe: str, bars: list[MarketBar], strategy_id: str) -> str:
        payload = {"symbol": symbol, "timeframe": timeframe, "strategy": strategy_id,
                   "bars": [[bar.timestamp, round(bar.close, 10), round(bar.volume, 10)] for bar in bars[-80:]]}
        return hashlib.sha256(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()

    def portfolio_snapshot(self) -> dict[str, Any]:
        state = self.store.snapshot(); paper = state["paper"]
        positions = paper.get("positions", [])
        gross = sum(float(row.get("position_size", 0)) * float(row.get("current_price", row.get("entry", 0)))
                    for row in positions)
        unrealized = sum(float(row.get("unrealized_pnl", 0)) for row in positions)
        realized_equity = float(paper.get("cash", paper.get("initial_cash", 10000)))
        equity = realized_equity + unrealized
        planned_risk = sum(float(row.get("max_planned_loss", 0)) for row in positions)
        return {"currency": paper.get("currency", "USD"), "realized_equity": realized_equity,
                "equity": equity, "unrealized_pnl": unrealized, "gross_exposure": gross,
                "gross_exposure_percent": gross / equity if equity > 0 else 0,
                "planned_risk": planned_risk, "open_positions": len(positions),
                "available_exposure": max(0.0, equity * self.MAX_GROSS_EXPOSURE_FRACTION - gross),
                "limits": {"max_open_positions": self.MAX_OPEN_POSITIONS,
                           "max_position_notional_percent": self.MAX_POSITION_NOTIONAL_FRACTION,
                           "max_gross_exposure_percent": self.MAX_GROSS_EXPOSURE_FRACTION,
                           "max_risk_per_trade_percent": self.MAX_RISK_FRACTION}}

    def _risk_gate(self, symbol: str, entry: float, stop: float, bars: list[MarketBar],
                   market: dict[str, Any], risk_fraction: float) -> dict[str, Any]:
        state = self.store.snapshot(); positions = state["paper"].get("positions", [])
        portfolio = self.portfolio_snapshot(); reasons: list[str] = []
        if any(row.get("asset") == symbol and row.get("status") == "OPEN" for row in positions):
            reasons.append("Bu varlıkta zaten açık paper pozisyon var.")
        if portfolio["open_positions"] >= self.MAX_OPEN_POSITIONS:
            reasons.append("Açık pozisyon sınırı dolu.")
        returns = [bars[i].close / bars[i - 1].close - 1 for i in range(max(1, len(bars) - 48), len(bars))]
        hourly_volatility = statistics.pstdev(returns) if len(returns) > 1 else 0.0
        volatility_scale = .5 if hourly_volatility > .02 else .75 if hourly_volatility > .01 else 1.0
        quote_volume = float(market.get("quote_volume_24h", 0) or 0)
        liquidity_scale = 1.0 if quote_volume <= 0 or quote_volume >= 50_000_000 else .5 if quote_volume >= 10_000_000 else 0.0
        if liquidity_scale == 0:
            reasons.append("24 saatlik likidite güvenlik eşiğinin altında.")
        equity = max(0.0, float(portfolio["equity"])); stop_distance = max(entry - stop, 0.0)
        clamped_risk = min(max(float(risk_fraction), .001), self.MAX_RISK_FRACTION)
        risk_budget = equity * clamped_risk * volatility_scale * liquidity_scale
        risk_size = risk_budget / stop_distance if stop_distance > 0 else 0.0
        position_cap = equity * self.MAX_POSITION_NOTIONAL_FRACTION / entry if entry > 0 else 0.0
        exposure_cap = float(portfolio["available_exposure"]) / entry if entry > 0 else 0.0
        size = min(risk_size, position_cap, exposure_cap)
        notional = size * entry
        if equity <= 0: reasons.append("Paper portföy özkaynağı pozitif değil.")
        if stop_distance <= 0: reasons.append("Geçerli stop mesafesi yok.")
        if size <= 0: reasons.append("Risk ve maruziyet limitleri pozisyon boyutuna izin vermiyor.")
        return {"approved": not reasons, "reasons": reasons, "position_size": size,
                "position_notional": notional, "risk_budget": risk_budget,
                "risk_fraction": clamped_risk, "hourly_volatility": hourly_volatility,
                "volatility_scale": volatility_scale, "liquidity_scale": liquidity_scale,
                "portfolio_before": portfolio, "correlation_bucket": "CRYPTO",
                "policy": "PORTFOLIO_RISK_GATE_V1"}

    @staticmethod
    def _review_paper_decision(decision: dict[str, Any], candidate: dict[str, Any] | None,
                               risk_gate: dict[str, Any], *, require_qualified: bool) -> dict[str, Any]:
        checks = {
            "exact_decision_version": decision.get("version") == "EREN_DECISION_V1",
            "evidence_fingerprint_present": len(str(decision.get("evidence_fingerprint", ""))) == 64,
            "evidence_fresh": bool(decision.get("evidence_fresh")),
            "strategy_qualified": bool(candidate and candidate.get("qualified")) if require_qualified else True,
            "signal_active": decision.get("proposed_direction") == "LONG",
            "portfolio_risk_gate": bool(risk_gate.get("approved")),
            "decision_checklist_complete": all(row.get("answer") is True for row in decision.get("decision_questions", [])),
            "paper_only": decision.get("live_activation") is False,
        }
        approved = all(checks.values())
        return {"reviewer": "CEMO_RULE_REVIEWER", "version": "CEMO_REVIEW_V1",
                "decision_id": decision["id"], "evidence_fingerprint": decision["evidence_fingerprint"],
                "checks": checks, "status": "APPROVED_PAPER" if approved else "REJECTED",
                "reasons": [name for name, passed in checks.items() if not passed],
                "self_approval": False, "live_activation": False, "reviewed_at": utc_now()}

    def paper_signal(self, asset: str, risk_fraction: float = DEFAULT_RISK_FRACTION, *,
                     bars: list[MarketBar] | None = None, market_snapshot: dict[str, Any] | None = None,
                     timeframe: str = "1h", require_qualified: bool = False) -> dict[str, Any]:
        bars = bars or self.market.ohlcv(asset, timeframe, limit=120)
        market = market_snapshot or self.market.price(asset)
        finance_state = self.store.snapshot()["engines"]["finance"]
        strategy_id = finance_state.get("paper_candidate")
        lab_has_run = "strategy_lab_decision" in finance_state
        if lab_has_run and not strategy_id:
            return {"asset": market["symbol"], "direction": "NO_TRADE", "status": "NO_TRADE",
                    "reason": "NO QUALIFIED STRATEGY", "live_activation": False,
                    "label": "PAPER GATE — NO REAL ORDER", "created_at": utc_now()}
        strategy_id = strategy_id or "sma_trend"
        definition = next((item for item in self._all_strategies() if item["id"] == strategy_id), self.STRATEGIES[0])
        candidate = self._candidate_record(strategy_id)
        active = self._signal(strategy_id, bars, len(bars))
        fast, slow = sum(b.close for b in bars[-10:]) / 10, sum(b.close for b in bars[-50:]) / 50
        direction = "LONG" if active else "NO_TRADE"
        entry = float(market["price"]); stop, target = entry * (1 - self.STOP_RATE), entry * (1 + self.TARGET_RATE)
        fingerprint = self._evidence_fingerprint(market["symbol"], timeframe, bars, strategy_id)
        last_bar_ms = int(bars[-1].timestamp) * (1000 if int(bars[-1].timestamp) < 10**12 else 1)
        age_ms = max(0, int(datetime.now(timezone.utc).timestamp() * 1000) - last_bar_ms)
        evidence_fresh = (age_ms <= 3 * 60 * 60 * 1000) if require_qualified else True
        regime = self._regime(bars)
        decision = {"id": f"decision-{uuid.uuid4().hex}", "version": "EREN_DECISION_V1",
                    "asset": market["symbol"], "timeframe": timeframe, "strategy_id": strategy_id,
                    "strategy": definition["name"], "proposed_direction": direction,
                    "thesis": {"bull": "Aktif strateji sinyali ve kısa ortalama üstünlüğü sürüyor.",
                               "base": "Stop ve portföy sınırı içinde yalnız paper denemesi yapılabilir.",
                               "bear": "Sinyal bozulması veya %2 stop tezi geçersiz kılar."},
                    "risks": ["Kripto oynaklığı", "slippage", "ücretler", "rejim değişimi"],
                    "entry": entry, "stop": stop, "target": target, "holding_review": f"Her {timeframe} kapanışında",
                    "evidence_fingerprint": fingerprint, "evidence_fresh": evidence_fresh,
                    "evidence_age_seconds": round(age_ms / 1000, 2), "evidence_last_bar": bars[-1].timestamp,
                    "market_regime": regime, "confidence": min(.90, .50 + abs(fast / slow - 1) * 10),
                    "live_activation": False, "created_at": utc_now()}
        risk_gate = self._risk_gate(market["symbol"], entry, stop, bars, market, risk_fraction)
        decision["decision_questions"] = [
            {"question": "Strateji OOS ve maliyetlerden sonra yeterli mi?",
             "answer": bool(candidate and candidate.get("qualified")) if require_qualified else True},
            {"question": "Piyasa kanıtı güncel mi?", "answer": evidence_fresh},
            {"question": "Giriş sinyali şu anda aktif mi?", "answer": active},
            {"question": "Stop ve hedef önceden tanımlı mı?", "answer": stop < entry < target},
            {"question": "Portföy maruziyeti ve pozisyon boyutu sınırlar içinde mi?",
             "answer": bool(risk_gate.get("approved"))},
            {"question": "Gerçek para ve broker emri kapalı mı?", "answer": True},
        ]
        review = self._review_paper_decision(decision, candidate, risk_gate, require_qualified=require_qualified)
        if review["status"] != "APPROVED_PAPER":
            reasons = review["reasons"] + list(risk_gate.get("reasons", []))
            no_trade = {"id": f"paper-{uuid.uuid4().hex}", "asset": market["symbol"], "direction": "NO_TRADE",
                        "status": "NO_TRADE", "reason": " · ".join(dict.fromkeys(reasons)) or "Sinyal aktif değil.",
                        "strategy": definition["name"], "decision": decision, "review": review,
                        "risk_gate": risk_gate, "live_activation": False,
                        "label": "PAPER GATE — NO REAL ORDER", "created_at": utc_now()}
            self.store.append("finance_decisions", no_trade)
            return no_trade
        size = float(risk_gate["position_size"])
        signal = {"id": f"paper-{uuid.uuid4().hex}", "asset": market["symbol"], "direction": direction,
                  "entry": entry, "entry_timestamp": utc_now(), "position_size": size, "stop": stop, "target": target,
                  "fees": size * entry * self.FEE_RATE if size else 0, "slippage": self.SLIPPAGE_RATE,
                  "strategy": definition["name"], "strategy_id": strategy_id, "market_regime": regime,
                  "confidence": decision["confidence"], "current_price": entry,
                  "unrealized_pnl": 0.0, "unrealized_pnl_percent": 0.0, "max_adverse_excursion": 0.0,
                  "max_favorable_excursion": 0.0, "leverage": 1, "max_planned_loss": size*(entry-stop),
                  "risk_reward": 2.0, "source": market["source"], "status": "OPEN",
                  "market_conditions": {"sma10": fast, "sma50": slow, "change_percent_24h": market["change_percent_24h"]},
                  "decision": decision, "review": review, "risk_gate": risk_gate,
                  "evidence_fingerprint": fingerprint, "live_activation": False,
                  "label": "PAPER — NO REAL ORDER", "created_at": utc_now()}
        self.store.update(lambda s: (s["paper"]["positions"].append(signal),
                                     s.setdefault("finance_decisions", []).append(signal)))
        return signal

    def autonomous_paper_cycle(self, assets: list[str] | None = None, timeframes: list[str] | None = None,
                               *, risk_fraction: float = DEFAULT_RISK_FRACTION,
                               bars_by_dimension: dict[tuple[str, str], list[MarketBar]] | None = None) -> dict[str, Any]:
        """Run one bounded research -> review -> risk -> paper cycle.

        The cycle intentionally has no broker, API-key or order endpoint. A
        failed evidence/review/risk check becomes NO_TRADE and is persisted.
        """
        requested_assets = assets or ["BTC", "ETH", "SOL"]
        symbols = list(dict.fromkeys(self.market._symbol(value) for value in requested_assets))[:3]
        frames = list(dict.fromkeys(timeframes or ["1h", "4h"]))[:2]
        started_at = utc_now(); cycle_id = f"finance-cycle-{uuid.uuid4().hex}"
        before = self.portfolio_snapshot()
        self.store.update(lambda state: state["engines"]["finance"].update(
            enabled=True, mode="RESEARCH", watchlist=symbols, live_activation=False))

        marked = self.mark_to_market() if before["open_positions"] else {
            "marked_at": started_at, "closed_ids": [], "positions": [], "closed": [],
            "performance": self.performance()["paper"]}
        data_errors: list[str] = []
        dimensions = dict(bars_by_dimension or {})
        if not dimensions:
            for symbol in symbols:
                for timeframe in frames:
                    try:
                        dimensions[(symbol, timeframe)] = self.market.ohlcv(symbol, timeframe, 1000)
                    except Exception as error:
                        data_errors.append(f"{symbol}/{timeframe}: {type(error).__name__}: {error}")

        lab: dict[str, Any] | None = None
        decisions: list[dict[str, Any]] = []
        if data_errors or set(dimensions) != {(symbol, timeframe) for symbol in symbols for timeframe in frames}:
            decisions.append({"status": "NO_TRADE", "reason": "Eksik veya hatalı piyasa verisi.",
                              "data_errors": data_errors, "live_activation": False})
        else:
            lab = self.explore_strategies(
                                          symbols[0], asset_budget=len(symbols),
                                          candidate_budget=len(self.NOVEL_STRATEGIES),
                                          timeframe_budget=len(frames), bars_by_dimension=dimensions,
                                          retest_reason="autonomous paper cycle")
            if not lab.get("paper_promoted"):
                decisions.append({"status": "NO_TRADE", "reason": lab["bounded_exploration_outcome"],
                                  "rejected_candidates": [{"id": row.get("candidate_id", row.get("id")),
                                      "reasons": row.get("rejection_reasons", [])} for row in lab.get("candidates", [])],
                                  "live_activation": False})
            else:
                for symbol in symbols:
                    try:
                        market = self.market.price(symbol)
                        decisions.append(self.paper_signal(symbol, risk_fraction, bars=dimensions[(symbol, frames[0])],
                                                           market_snapshot=market, timeframe=frames[0],
                                                           require_qualified=True))
                    except Exception as error:
                        decisions.append({"asset": symbol, "status": "NO_TRADE",
                                          "reason": f"Karar döngüsü güvenli kapandı: {type(error).__name__}: {error}",
                                          "live_activation": False})

        qualification = self.qualification()
        after = self.portfolio_snapshot(); paper_performance = self.performance()["paper"]
        opened = [row for row in decisions if row.get("status") == "OPEN"]
        rejected = [row for row in decisions if row.get("status") != "OPEN"]
        previous = self.store.snapshot().get("finance_cycles", [])
        prior = previous[-1] if previous else None
        comparison = {"previous_cycle_id": prior.get("id") if prior else None,
                      "equity_change": after["equity"] - float(prior.get("portfolio_after", {}).get("equity", before["equity"])) if prior else 0.0,
                      "open_position_change": after["open_positions"] - int(prior.get("portfolio_after", {}).get("open_positions", before["open_positions"])) if prior else 0,
                      "closed_trade_change": len(marked.get("closed_ids", []))}
        lesson = {"what_worked": [f"{len(opened)} paper fırsatı tüm kapılardan geçti."] if opened else [],
                  "what_failed": [row.get("reason", "Risk/inceleme kapısı reddetti.") for row in rejected],
                  "next_action": "Açık paper pozisyonları izle ve yeni veride tekrar test et."
                                 if opened else "Yeni piyasa verisinde sınırlı keşfi tekrarla; ölçütleri gevşetme."}
        cycle = {"id": cycle_id, "status": "PAPER_POSITION_OPENED" if opened else "NO_TRADE",
                 "label": "AUTONOMOUS PAPER CYCLE — NO REAL ORDER", "started_at": started_at,
                 "finished_at": utc_now(), "assets": symbols, "timeframes": frames,
                 "strategy_lab": lab, "decisions": decisions, "marked_positions": marked,
                 "portfolio_before": before, "portfolio_after": after, "paper_performance": paper_performance,
                 "qualification": qualification, "comparison": comparison, "lesson": lesson,
                 "safety": {"real_orders_sent": 0, "real_money_used": 0,
                            "live_trading_enabled": False, "broker_client_present": False},
                 "data_errors": data_errors}
        def persist(state: dict[str, Any]) -> None:
            state.setdefault("finance_cycles", []).append(cycle)
            del state["finance_cycles"][:-100]
            state["engines"]["finance"].update(enabled=True,
                mode="PAPER" if opened else "RESEARCH", last_cycle_id=cycle_id,
                last_cycle_status=cycle["status"], last_cycle_at=cycle["finished_at"], live_activation=False)
        self.store.update(persist)
        return cycle

    def mark_to_market(self, prices: dict[str, float] | None = None) -> dict[str, Any]:
        """Revalue every open paper position and close stops/targets atomically."""
        state = self.store.snapshot(); supplied = {self.market._symbol(k): float(v) for k, v in (prices or {}).items()}
        quotes: dict[str, float] = {}
        for position in state["paper"]["positions"]:
            symbol = position["asset"]
            quotes[symbol] = supplied.get(symbol) if symbol in supplied else float(self.market.price(symbol)["price"])
        closed_ids, now = [], utc_now()
        def mutate(current: dict[str, Any]) -> None:
            remaining = []
            for p in current["paper"]["positions"]:
                price, entry, size = quotes[p["asset"]], float(p["entry"]), float(p["position_size"])
                direction = p.get("direction", "LONG"); signed = 1 if direction == "LONG" else -1
                move = signed * (price / entry - 1)
                p["current_price"], p["marked_at"] = price, now
                p["unrealized_pnl_percent"] = move
                p["unrealized_pnl"] = size * entry * move - float(p.get("fees", 0))
                p["max_favorable_excursion"] = max(float(p.get("max_favorable_excursion", 0)), move)
                p["max_adverse_excursion"] = min(float(p.get("max_adverse_excursion", 0)), move)
                stop_hit = price <= p["stop"] if direction == "LONG" else price >= p["stop"]
                target_hit = price >= p["target"] if direction == "LONG" else price <= p["target"]
                if stop_hit or target_hit:
                    reason = "STOP" if stop_hit else "TARGET"
                    exit_price = price * (1 - signed * self.SLIPPAGE_RATE)
                    exit_fee = size * exit_price * self.FEE_RATE
                    pnl = signed * size * (exit_price - entry) - float(p.get("fees", 0)) - exit_fee
                    p.update(status="CLOSED", exit=exit_price, exit_timestamp=now, exit_reason=reason,
                             reason=reason, exit_fee=exit_fee, fees=float(p.get("fees", 0)) + exit_fee,
                             pnl=pnl, pnl_percent=pnl / (size * entry) if size * entry else 0)
                    current["paper"]["cash"] += pnl; current["paper"]["closed"].append(p); closed_ids.append(p["id"])
                else: remaining.append(p)
            current["paper"]["positions"] = remaining
            current["paper"]["performance"] = _metrics(current["paper"]["closed"], float(current["paper"].get("initial_cash", 10000)))
        updated = self.store.update(mutate)
        return {"marked_at": now, "prices": quotes, "closed_ids": closed_ids,
                "positions": updated["paper"]["positions"], "closed": updated["paper"]["closed"],
                "performance": updated["paper"]["performance"]}

    def close_position(self, position_id: str, reason: str = "MANUAL", price: float | None = None) -> dict[str, Any]:
        state = self.store.snapshot(); position = next((x for x in state["paper"]["positions"] if x["id"] == position_id), None)
        if not position: raise KeyError("Açık paper pozisyon bulunamadı.")
        value = float(price if price is not None else self.market.price(position["asset"])["price"])
        # Force a deterministic close through the same accounting path.
        target_key = "target" if position.get("direction") == "LONG" else "stop"
        self.store.update(lambda s: next(x for x in s["paper"]["positions"] if x["id"] == position_id).update({target_key: value}))
        result = self.mark_to_market({position["asset"]: value})
        closed = next(x for x in result["closed"] if x["id"] == position_id)
        if reason != closed["reason"]:
            self.store.update(lambda s: next(x for x in s["paper"]["closed"] if x["id"] == position_id).update(reason=reason, exit_reason=reason))
            closed.update(reason=reason, exit_reason=reason)
        return closed

    def performance(self) -> dict[str, Any]:
        state = self.store.snapshot(); closed = state["paper"]["closed"]
        paper = _metrics(closed, float(state["paper"].get("initial_cash", 10000)))
        grouped: dict[str, Any] = {}
        for trade in closed:
            key = f"{trade.get('strategy', 'unknown')} / {trade.get('market_regime', 'unknown')}"
            grouped[key] = _metrics([x for x in closed if f"{x.get('strategy', 'unknown')} / {x.get('market_regime', 'unknown')}" == key],
                                    float(state["paper"].get("initial_cash", 10000)))
        return {"paper": paper, "backtest": [x for x in state.get("backtests", [])[-30:]],
                "out_of_sample": [x.get("out_of_sample_metrics", {}) for x in state.get("backtests", [])[-30:]],
                "strategy_regime": grouped, "labels": {"paper": "PAPER — NOT LIVE", "backtest": "BACKTEST — NOT LIVE"}}

    def request_live_trade(self, proposal: dict[str, Any]) -> dict[str, Any]:
        decision = self.policy.evaluate("live_trade")
        required = ("asset", "direction", "entry", "stop", "target", "position_size", "max_planned_loss", "risk_reward", "confidence")
        details = {key: proposal.get(key) for key in required} | {"leverage": proposal.get("leverage", 1),
                  "why_this_trade": proposal.get("why_this_trade", proposal.get("why", "Strateji sinyali")),
                  "why_now": proposal.get("why_now"), "invalidation": proposal.get("invalidation"),
                  "evidence": proposal.get("evidence", {})}
        approval = {"id": f"approval-{uuid.uuid4().hex}", "type": "finance_real_trade", "status": "PENDING",
                    "what": "Gerçek para işlemi önerisi (execution devre dışı)", "why": details["why_this_trade"],
                    "risk": decision.risk.value, "cost": details["max_planned_loss"], "expected_result": details["target"],
                    "alternatives": ["Paper modunda devam et", "Fırsatı reddet"], "details": details,
                    "execution_enabled": False, "created_at": utc_now()}
        self.store.append("approvals", approval)
        return approval

    def qualification(self) -> dict[str, Any]:
        state = self.store.snapshot(); tests = state.get("backtests", []); labs = state.get("strategy_labs", [])
        closed = state.get("paper", {}).get("closed", [])
        lab_candidates = [candidate for lab in labs for candidate in lab.get("candidates", [])]
        assets = {x.get("asset") for x in tests}
        assets.update(asset for lab in labs for asset in lab.get("assets_tested", []) if asset)
        regimes = {x.get("regime") for x in tests}
        regimes.update(regime for lab in labs for regime in lab.get("regimes_tested", []) if regime)
        strategies = {x.get("strategy") for x in tests}
        strategies.update(x.get("name") for x in lab_candidates if x.get("name"))
        total_trades = sum(int(x.get("trade_count", x.get("trades", 0))) for x in tests + lab_candidates)
        oos = [x for x in tests if int(x.get("out_of_sample_bars", 0)) >= 50
               and int(x.get("out_of_sample_metrics", {}).get("trade_count", 0)) > 0]
        oos += [x for x in lab_candidates if int(x.get("out_of_sample_metrics", {}).get("trade_count", 0)) >= 3]
        paper_metrics = _metrics(closed, float(state["paper"].get("initial_cash", 10000)))
        reasons = []
        evidence_runs = len(tests) + len(labs)
        if evidence_runs < 3: reasons.append("En az 3 bağımsız backtest/strateji laboratuvarı koşusu gerekli.")
        if len(assets) < 2: reasons.append("Birden fazla varlık kanıtı gerekli.")
        if len(regimes) < 2: reasons.append("Birden fazla piyasa rejimi gerekli.")
        if total_trades < 30: reasons.append("En az 30 backtest işlemi gerekli.")
        if len(oos) < 3: reasons.append("Out-of-sample kanıtı yetersiz.")
        if len(closed) < 20: reasons.append("En az 20 kapanmış paper işlem gerekli.")
        if paper_metrics["net_return_after_costs"] <= 0: reasons.append("Paper net getiri maliyetlerden sonra pozitif değil.")
        if paper_metrics["max_drawdown"] > .20: reasons.append("Paper drawdown %20 sınırını aşıyor.")
        if paper_metrics["profit_factor"] is None or paper_metrics["profit_factor"] < 1.1: reasons.append("Paper profit factor 1.10 altında.")
        overfit_risk = "HIGH" if len(strategies) == 1 and len(regimes) < 2 else "MEDIUM" if len(oos) < 5 else "LOW"
        if overfit_risk == "HIGH": reasons.append("Overfitting riski yüksek.")
        result = {"qualified": not reasons, "reasons": reasons, "evidence": {"backtests": len(tests),
                  "strategy_lab_runs": len(labs), "evidence_runs": evidence_runs, "assets": sorted(x for x in assets if x),
                  "regimes": sorted(x for x in regimes if x), "strategies": sorted(x for x in strategies if x),
                  "backtest_trades": total_trades, "out_of_sample_runs": len(oos), "closed_paper_trades": len(closed),
                  "paper_metrics": paper_metrics}, "overfitting_risk": overfit_risk, "live_activation": False,
                  "label": "QUALIFICATION — PAPER EVIDENCE; LIVE DISABLED"}
        self.store.update(lambda s: s["engines"]["finance"].update(mode="QUALIFIED" if result["qualified"] else "PAPER",
                                                                    qualification=result, live_activation=False))
        return result
