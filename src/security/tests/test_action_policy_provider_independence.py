from __future__ import annotations

import inspect

from src.providers.cost_optimizer import CostOptimizer
from src.security.action_policy import ActionPolicy, RiskLevel


class TestActionPolicyIsDecoupledFromProviderRouting:
    """Free-first provider routing must never widen finance/trade
    authority. ActionPolicy gates purely by action name -- it takes no
    provider/model parameter, so no routing change (which provider/cost
    tier gets picked) can affect what it allows."""

    def test_evaluate_signature_has_no_provider_or_model_parameter(self):
        params = set(inspect.signature(ActionPolicy.evaluate).parameters)
        assert "provider" not in params
        assert "model" not in params
        assert "cost_class" not in params

    def test_live_trade_always_requires_confirmation(self):
        decision = ActionPolicy().evaluate("live_trade", standing_permission=True)
        assert decision.allowed is True
        assert decision.requires_confirmation is True
        assert decision.risk == RiskLevel.HIGH

    def test_money_movement_actions_are_never_auto_allowed(self):
        for action in ("withdraw_money", "transfer_money", "send_crypto"):
            decision = ActionPolicy().evaluate(action, standing_permission=True)
            assert decision.allowed is False
            assert decision.risk == RiskLevel.CRITICAL

    def test_free_tier_classification_cannot_be_smuggled_in_as_an_action(self):
        # A free/cheap provider decision must not be interpretable as a
        # low-risk action name that bypasses confirmation.
        for cost_class in ("free", "plan", "paid", "unknown"):
            decision = ActionPolicy().evaluate(cost_class)
            assert decision.allowed is False
            assert decision.requires_confirmation is True

    def test_cost_optimizer_decide_never_touches_action_policy(self):
        # CostOptimizer's public surface is a routing decision only; it
        # must expose nothing that grants trade/money authority.
        public_members = {name for name, _ in inspect.getmembers(CostOptimizer) if not name.startswith("_")}
        assert "evaluate" not in public_members
        assert "approve" not in public_members
