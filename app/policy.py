from __future__ import annotations

from app.domain import PolicyAction, PolicyDecision


class ActionPolicy:
    """Deterministic authorization boundary for side-effecting support actions."""

    def __init__(self, refund_human_review_threshold: float) -> None:
        self.refund_human_review_threshold = refund_human_review_threshold

    def refund(self, amount: float) -> PolicyDecision:
        if amount > self.refund_human_review_threshold:
            return PolicyDecision(
                action=PolicyAction.REQUIRE_HUMAN,
                reasons=["refund_amount_above_human_review_threshold"],
            )
        return PolicyDecision(
            action=PolicyAction.REQUIRE_CONFIRMATION,
            reasons=["refund_is_mutating_action", "customer_confirmation_required"],
        )

    @staticmethod
    def return_request() -> PolicyDecision:
        return PolicyDecision(
            action=PolicyAction.REQUIRE_CONFIRMATION,
            reasons=["return_is_mutating_action", "customer_confirmation_required"],
        )
