from __future__ import annotations

import json
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

    def __init__(self, store: ControlCenterStore, market: BinancePublicMarketData | None = None) -> None:
        self.store, self.market, self.policy = store, market or BinancePublicMarketData(), ActionPolicy()

    def backtest(self, asset: str, bars: list[MarketBar] | None = None) -> dict[str, Any]:
        bars = bars or self.market.ohlcv(asset)
        if len(bars) < 80:
            raise ValueError("Backtest için en az 80 gerçek OHLCV bar gerekli.")
        closes, split = [b.close for b in bars], int(len(bars) * .7)
        trades, position = [], None
        for i in range(50, len(bars)):
            fast, slow = sum(closes[i-10:i]) / 10, sum(closes[i-50:i]) / 50
            prev_fast, prev_slow = sum(closes[i-11:i-1]) / 10, sum(closes[i-51:i-1]) / 50
            if position is None and prev_fast <= prev_slow and fast > slow:
                position = (closes[i] * (1 + self.SLIPPAGE_RATE), i)
            elif position and prev_fast >= prev_slow and fast < slow:
                entry, opened = position; exit_price = closes[i] * (1 - self.SLIPPAGE_RATE)
                gross = exit_price / entry - 1; net = gross - 2 * self.FEE_RATE
                trades.append({"entry_index": opened, "exit_index": i, "return": net, "pnl_percent": net,
                               "pnl": net, "out_of_sample": opened >= split}); position = None
        train, oos = [x for x in trades if not x["out_of_sample"]], [x for x in trades if x["out_of_sample"]]
        result = {"id": f"bt-{uuid.uuid4().hex}", "asset": self.market._symbol(asset), "source": "Binance official OHLCV",
                  "strategy": "SMA 10/50 crossover", "regime": self._regime(bars), "sample_bars": len(bars),
                  "train_bars": split, "out_of_sample_bars": len(bars)-split, "fees_rate": self.FEE_RATE,
                  "slippage_rate": self.SLIPPAGE_RATE, **_metrics(trades), "trades": len(trades),
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
            elif position is not None and not active:
                entry, opened = position
                exit_price = bars[index].close * (1 - self.SLIPPAGE_RATE)
                net = exit_price / entry - 1 - 2 * self.FEE_RATE
                trades.append({"entry_index": opened, "exit_index": index, "return": net,
                               "pnl_percent": net, "pnl": net, "out_of_sample": opened >= split,
                               "regime": self._regime_at(bars, opened)})
                position = None
        if position is not None:
            entry, opened = position
            exit_price = bars[-1].close * (1 - self.SLIPPAGE_RATE)
            net = exit_price / entry - 1 - 2 * self.FEE_RATE
            trades.append({"entry_index": opened, "exit_index": len(bars) - 1, "return": net,
                           "pnl_percent": net, "pnl": net, "out_of_sample": opened >= split,
                           "regime": self._regime_at(bars, opened)})
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

    def paper_signal(self, asset: str, risk_fraction: float = .01) -> dict[str, Any]:
        bars, market = self.market.ohlcv(asset, limit=100), self.market.price(asset)
        finance_state = self.store.snapshot()["engines"]["finance"]
        strategy_id = finance_state.get("paper_candidate")
        lab_has_run = "strategy_lab_decision" in finance_state
        if lab_has_run and not strategy_id:
            return {"asset": market["symbol"], "direction": "NO_TRADE", "status": "NO_TRADE",
                    "reason": "NO QUALIFIED STRATEGY", "live_activation": False,
                    "label": "PAPER GATE — NO REAL ORDER", "created_at": utc_now()}
        strategy_id = strategy_id or "sma_trend"
        definition = next((item for item in self.STRATEGIES if item["id"] == strategy_id), self.STRATEGIES[0])
        active = self._signal(strategy_id, bars, len(bars))
        fast, slow = sum(b.close for b in bars[-10:]) / 10, sum(b.close for b in bars[-50:]) / 50
        direction = "LONG" if active else "NO_TRADE"
        cash = float(self.store.snapshot()["paper"]["cash"]); entry = market["price"]
        stop, target = entry * .98, entry * 1.04
        size = (cash * min(max(risk_fraction, .001), .02)) / max(entry-stop, .000001) if direction == "LONG" else 0
        signal = {"id": f"paper-{uuid.uuid4().hex}", "asset": market["symbol"], "direction": direction,
                  "entry": entry, "entry_timestamp": utc_now(), "position_size": size, "stop": stop, "target": target,
                  "fees": size * entry * self.FEE_RATE if size else 0, "slippage": self.SLIPPAGE_RATE,
                  "strategy": definition["name"], "market_regime": self._regime(bars),
                  "confidence": min(.95, .5 + abs(fast / slow - 1) * 10), "current_price": entry,
                  "unrealized_pnl": 0.0, "unrealized_pnl_percent": 0.0, "max_adverse_excursion": 0.0,
                  "max_favorable_excursion": 0.0, "leverage": 1, "max_planned_loss": size*(entry-stop),
                  "risk_reward": 2.0, "source": market["source"], "status": "OPEN" if direction == "LONG" else "NO_TRADE",
                  "market_conditions": {"sma10": fast, "sma50": slow, "change_percent_24h": market["change_percent_24h"]},
                  "label": "PAPER — NO REAL ORDER", "created_at": utc_now()}
        if direction == "LONG":
            self.store.update(lambda s: s["paper"]["positions"].append(signal))
        return signal

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
        state = self.store.snapshot(); tests, closed = state.get("backtests", []), state.get("paper", {}).get("closed", [])
        assets = {x.get("asset") for x in tests}; regimes = {x.get("regime") for x in tests}; strategies = {x.get("strategy") for x in tests}
        total_trades = sum(int(x.get("trade_count", x.get("trades", 0))) for x in tests)
        oos = [x for x in tests if int(x.get("out_of_sample_bars", 0)) >= 50 and int(x.get("out_of_sample_metrics", {}).get("trade_count", 0)) > 0]
        paper_metrics = _metrics(closed, float(state["paper"].get("initial_cash", 10000)))
        reasons = []
        if len(tests) < 3: reasons.append("En az 3 backtest gerekli.")
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
        result = {"qualified": not reasons, "reasons": reasons, "evidence": {"backtests": len(tests), "assets": sorted(assets),
                  "regimes": sorted(x for x in regimes if x), "strategies": sorted(x for x in strategies if x),
                  "backtest_trades": total_trades, "out_of_sample_runs": len(oos), "closed_paper_trades": len(closed),
                  "paper_metrics": paper_metrics}, "overfitting_risk": overfit_risk, "live_activation": False,
                  "label": "QUALIFICATION — PAPER EVIDENCE; LIVE DISABLED"}
        self.store.update(lambda s: s["engines"]["finance"].update(mode="QUALIFIED" if result["qualified"] else "PAPER",
                                                                    qualification=result, live_activation=False))
        return result
