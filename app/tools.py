from __future__ import annotations

from app.domain import OrderView, TicketView
from app.store import SupportStore


class SupportTools:
    """Allowlisted business tools. Authorization is enforced by the application layer."""

    def __init__(self, store: SupportStore) -> None:
        self.store = store

    def get_order(self, *, order_id: str, customer_id: str) -> OrderView | None:
        return self.store.get_order(order_id, customer_id)

    def quote_refund(self, *, order_id: str, customer_id: str) -> dict[str, float | str]:
        order = self.get_order(order_id=order_id, customer_id=customer_id)
        if order is None:
            raise ValueError("order_not_found")
        if order.refundable_amount <= 0:
            raise ValueError("order_not_refundable")
        return {"order_id": order.order_id, "amount": order.refundable_amount}

    def execute_refund(
        self,
        *,
        order_id: str,
        customer_id: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        return self.store.execute_refund(
            order_id=order_id,
            customer_id=customer_id,
            idempotency_key=idempotency_key,
        )

    def execute_return(
        self,
        *,
        order_id: str,
        customer_id: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        return self.store.execute_return(
            order_id=order_id,
            customer_id=customer_id,
            idempotency_key=idempotency_key,
        )

    def create_ticket(
        self,
        *,
        customer_id: str,
        conversation_id: str,
        reason: str,
    ) -> TicketView:
        return self.store.create_ticket(customer_id, conversation_id, reason)
