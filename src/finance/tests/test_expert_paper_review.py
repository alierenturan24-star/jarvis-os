from types import SimpleNamespace

from src.finance.manager import FinanceManager


def test_claude_review_is_advisory_and_cannot_override_trade_decision():
    manager = FinanceManager()
    manager.router.manager = SimpleNamespace(route_and_generate=lambda **kwargs: SimpleNamespace(
        output="Kanıt yetersiz.\nUZMAN GÖRÜŞÜ: NO_TRADE",
        success=True,
        provider_used="claude_code",
    ))
    cycle = {
        "assets": ["BTCUSDT"], "timeframes": ["1h", "4h"],
        "strategy_lab": {"decision": "NO QUALIFIED STRATEGY", "candidates": [{
            "name": "test", "family": "trend", "qualified": False,
            "qualification_reasons": ["OOS net return is not positive"],
            "out_of_sample_metrics": {"net_return_after_costs": -0.01},
        }]},
        "paper_performance": {},
        "safety": {"real_orders_sent": 0, "real_money_used": 0},
    }

    review = manager.review_paper_cycle(cycle, "claude_code")

    assert review["success"] is True
    assert review["provider_used"] == "claude_code"
    assert review["can_override_trade_decision"] is False
    assert review["live_activation"] is False
    assert cycle["strategy_lab"]["decision"] == "NO QUALIFIED STRATEGY"

