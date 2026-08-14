from __future__ import annotations

from time import perf_counter

from app.domain import OrderView, TicketPriority, TicketView
from app.store import SupportStore
from app.tickets import TicketWorkflow


class SupportTools:
    """Allowlisted business tools with customer scoping and durable audit events."""

    def __init__(self, store: SupportStore, tickets: TicketWorkflow) -> None:
        self.store = store
        self.tickets = tickets

    def get_order(
        self,
        *,
        order_id: str,
        customer_id: str,
        trace_id: str,
        actor_id: str,
    ) -> OrderView | None:
        started = perf_counter()
        order = self.store.get_order(order_id, customer_id)
        self._audit(
            trace_id=trace_id,
            actor_id=actor_id,
            operation="order.get",
            resource_type="order",
            resource_id=order_id,
            outcome="success" if order else "not_found",
            started=started,
        )
        return order

    def quote_refund(
        self,
        *,
        order_id: str,
        customer_id: str,
        trace_id: str,
        actor_id: str,
    ) -> dict[str, float | str]:
        started = perf_counter()
        order = self.store.get_order(order_id, customer_id)
        if order is None:
            self._audit(
                trace_id=trace_id,
                actor_id=actor_id,
                operation="refund.quote",
                resource_type="order",
                resource_id=order_id,
                outcome="not_found",
                started=started,
            )
            raise ValueError("order_not_found")
        if order.refundable_amount <= 0:
            self._audit(
                trace_id=trace_id,
                actor_id=actor_id,
                operation="refund.quote",
                resource_type="order",
                resource_id=order_id,
                outcome="not_refundable",
                started=started,
            )
            raise ValueError("order_not_refundable")
        self._audit(
            trace_id=trace_id,
            actor_id=actor_id,
            operation="refund.quote",
            resource_type="order",
            resource_id=order_id,
            outcome="success",
            started=started,
            details={"amount": order.refundable_amount},
        )
        return {"order_id": order.order_id, "amount": order.refundable_amount}

    def execute_refund(
        self,
        *,
        order_id: str,
        customer_id: str,
        idempotency_key: str,
        trace_id: str,
        actor_id: str,
    ) -> dict[str, object]:
        started = perf_counter()
        try:
            result = self.store.execute_refund(
                order_id=order_id,
                customer_id=customer_id,
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            self._audit(
                trace_id=trace_id,
                actor_id=actor_id,
                operation="refund.execute",
                resource_type="order",
                resource_id=order_id,
                outcome="rejected",
                started=started,
                details={"reason": str(exc)},
            )
            raise
        self._audit(
            trace_id=trace_id,
            actor_id=actor_id,
            operation="refund.execute",
            resource_type="order",
            resource_id=order_id,
            outcome="success",
            started=started,
            details={"idempotency_key": idempotency_key},
        )
        return result

    def execute_return(
        self,
        *,
        order_id: str,
        customer_id: str,
        idempotency_key: str,
        trace_id: str,
        actor_id: str,
    ) -> dict[str, object]:
        started = perf_counter()
        try:
            result = self.store.execute_return(
                order_id=order_id,
                customer_id=customer_id,
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            self._audit(
                trace_id=trace_id,
                actor_id=actor_id,
                operation="return.execute",
                resource_type="order",
                resource_id=order_id,
                outcome="rejected",
                started=started,
                details={"reason": str(exc)},
            )
            raise
        self._audit(
            trace_id=trace_id,
            actor_id=actor_id,
            operation="return.execute",
            resource_type="order",
            resource_id=order_id,
            outcome="success",
            started=started,
            details={"idempotency_key": idempotency_key},
        )
        return result

    def create_ticket(
        self,
        *,
        customer_id: str,
        conversation_id: str,
        reason: str,
        trace_id: str,
        actor_id: str,
        priority: TicketPriority = TicketPriority.NORMAL,
    ) -> TicketView:
        started = perf_counter()
        ticket = self.tickets.create_handoff(
            customer_id=customer_id,
            conversation_id=conversation_id,
            reason=reason,
            priority=priority,
        )
        self._audit(
            trace_id=trace_id,
            actor_id=actor_id,
            operation="ticket.create",
            resource_type="ticket",
            resource_id=ticket.ticket_id,
            outcome="success",
            started=started,
            details={"priority": priority.value},
        )
        return ticket

    def _audit(
        self,
        *,
        trace_id: str,
        actor_id: str,
        operation: str,
        resource_type: str,
        resource_id: str | None,
        outcome: str,
        started: float,
        details: dict[str, object] | None = None,
    ) -> None:
        payload = dict(details or {})
        payload["latency_ms"] = round((perf_counter() - started) * 1000, 3)
        self.store.record_audit(
            trace_id=trace_id,
            actor_id=actor_id,
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            details=payload,
        )
