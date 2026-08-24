from __future__ import annotations

from src.security.action_policy import ActionPolicy, RiskLevel

_DESTRUCTIVE_GIT_ACTIONS = (
    "git_reset_hard",
    "git_clean_force",
    "git_force_push",
    "git_branch_delete",
    "git_history_rewrite",
)


class TestDestructiveGitActionsAreNeverAutoAllowed:
    """Test G: destructive/irreversible git actions must stay
    approval-gated even with a standing permission -- same CRITICAL tier
    as delete_system_files, never a lower tier that could be satisfied by
    a one-time standing permission grant."""

    def test_destructive_git_actions_are_critical_and_blocked(self):
        for action in _DESTRUCTIVE_GIT_ACTIONS:
            decision = ActionPolicy().evaluate(action, standing_permission=True)
            assert decision.allowed is False, action
            assert decision.risk == RiskLevel.CRITICAL, action
            assert decision.requires_confirmation is True, action

    def test_destructive_git_actions_are_registered_not_falling_through_default(self):
        # Distinguish an intentional CRITICAL classification from the
        # generic "undefined action" fallback (same allowed=False shape,
        # different intent) -- these must be explicitly named.
        for action in _DESTRUCTIVE_GIT_ACTIONS:
            assert action in ActionPolicy.CRITICAL_ACTIONS
