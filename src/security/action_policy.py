from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ActionDecision:
    allowed: bool
    requires_confirmation: bool
    risk: RiskLevel
    reason: str


class ActionPolicy:
    """
    JARVIS'in hangi işlemleri otomatik yapabileceğini belirler.

    LOW:
        Otomatik yapılabilir.

    MEDIUM:
        Kullanıcının önceden verdiği otomasyon izni varsa yapılabilir.

    HIGH:
        Her işlem öncesinde açık kullanıcı onayı gerekir.

    CRITICAL:
        JARVIS tarafından otomatik yapılmaz.
    """

    LOW_RISK_ACTIONS = {
        "market_data_read",
        "trend_research",
        "news_research",
        "idea_generation",
        "script_generation",
        "video_draft",
        "code_analysis",
        "code_draft",
        "paper_trade",
        "paper_order_cancel",
        "report_generation",
    }

    MEDIUM_RISK_ACTIONS = {
        "publish_scheduled_video",
        "upload_private_video",
        "create_project_file",
        "edit_project_file",
        "run_project_tests",
        "install_sandbox_package",
        "create_social_draft",
    }

    HIGH_RISK_ACTIONS = {
        "publish_public_video",
        "git_commit",
        "git_push",
        "install_production_package",
        "change_claude_skill",
        "live_trade",
        "live_order_cancel",
        "create_online_account",
        "change_account_setting",
    }

    CRITICAL_ACTIONS = {
        "withdraw_money",
        "transfer_money",
        "send_crypto",
        "reveal_password",
        "reveal_api_key",
        "disable_security",
        "bypass_captcha",
        "delete_system_files",
        "disable_two_factor_auth",
    }

    def evaluate(
        self,
        action: str,
        standing_permission: bool = False,
    ) -> ActionDecision:
        normalized = action.strip().lower()

        if normalized in self.CRITICAL_ACTIONS:
            return ActionDecision(
                allowed=False,
                requires_confirmation=True,
                risk=RiskLevel.CRITICAL,
                reason=(
                    "Bu işlem güvenlik veya para transferi içerdiği için "
                    "JARVIS tarafından otomatik gerçekleştirilemez."
                ),
            )

        if normalized in self.HIGH_RISK_ACTIONS:
            return ActionDecision(
                allowed=True,
                requires_confirmation=True,
                risk=RiskLevel.HIGH,
                reason="Bu işlem için her seferinde açık onay gerekir.",
            )

        if normalized in self.MEDIUM_RISK_ACTIONS:
            return ActionDecision(
                allowed=True,
                requires_confirmation=not standing_permission,
                risk=RiskLevel.MEDIUM,
                reason=(
                    "Önceden tanımlanmış otomasyon izni varsa "
                    "işlem otomatik yürütülebilir."
                ),
            )

        if normalized in self.LOW_RISK_ACTIONS:
            return ActionDecision(
                allowed=True,
                requires_confirmation=False,
                risk=RiskLevel.LOW,
                reason="Düşük riskli işlem otomatik yürütülebilir.",
            )

        return ActionDecision(
            allowed=False,
            requires_confirmation=True,
            risk=RiskLevel.HIGH,
            reason="Tanımlanmamış işlem güvenlik nedeniyle engellendi.",
        )