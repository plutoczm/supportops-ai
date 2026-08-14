from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Float, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.domain import (
    OrderView,
    PendingActionKind,
    PendingActionStatus,
    PendingActionView,
    TicketStatus,
    TicketView,
)


class Base(DeclarativeBase):
    pass


class OrderRow(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32))
    amount: Mapped[float] = mapped_column(Float)
    refundable_amount: Mapped[float] = mapped_column(Float)
    refund_status: Mapped[str] = mapped_column(String(32), default="none")
    return_status: Mapped[str] = mapped_column(String(32), default="none")


class TicketRow(Base):
    __tablename__ = "tickets"

    ticket_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(128), index=True)
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    reason: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(32), default=TicketStatus.OPEN.value)


class PendingActionRow(Base):
    __tablename__ = "pending_actions"

    action_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    customer_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default=PendingActionStatus.PENDING.value)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ActionReceiptRow(Base):
    __tablename__ = "action_receipts"

    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    action_kind: Mapped[str] = mapped_column(String(32))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)


class SupportStore:
    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, connect_args=connect_args)
        self._session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def seed_demo_data(self) -> None:
        with self._session.begin() as session:
            exists = session.scalar(select(OrderRow.order_id).limit(1))
            if exists:
                return
            session.add_all(
                [
                    OrderRow(
                        order_id="ORD-1001",
                        customer_id="CUST-001",
                        status="delivered",
                        amount=199.0,
                        refundable_amount=199.0,
                    ),
                    OrderRow(
                        order_id="ORD-1002",
                        customer_id="CUST-001",
                        status="shipped",
                        amount=89.0,
                        refundable_amount=0.0,
                    ),
                    OrderRow(
                        order_id="ORD-2001",
                        customer_id="CUST-002",
                        status="delivered",
                        amount=899.0,
                        refundable_amount=899.0,
                    ),
                ]
            )

    def get_order(self, order_id: str, customer_id: str) -> OrderView | None:
        with self._session() as session:
            row = session.get(OrderRow, order_id)
            if row is None or row.customer_id != customer_id:
                return None
            return self._to_order(row)

    def create_ticket(self, customer_id: str, conversation_id: str, reason: str) -> TicketView:
        ticket_id = f"TKT-{uuid4().hex[:12].upper()}"
        with self._session.begin() as session:
            row = TicketRow(
                ticket_id=ticket_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                reason=reason,
                status=TicketStatus.OPEN.value,
            )
            session.add(row)
        return self.get_ticket(ticket_id)  # type: ignore[return-value]

    def get_ticket(self, ticket_id: str) -> TicketView | None:
        with self._session() as session:
            row = session.get(TicketRow, ticket_id)
            if row is None:
                return None
            return TicketView(
                ticket_id=row.ticket_id,
                customer_id=row.customer_id,
                conversation_id=row.conversation_id,
                reason=row.reason,
                status=TicketStatus(row.status),
            )

    def create_pending_action(
        self,
        *,
        conversation_id: str,
        customer_id: str,
        kind: PendingActionKind,
        payload: dict[str, Any],
    ) -> PendingActionView:
        action_id = f"ACT-{uuid4().hex[:12].upper()}"
        with self._session.begin() as session:
            session.add(
                PendingActionRow(
                    action_id=action_id,
                    conversation_id=conversation_id,
                    customer_id=customer_id,
                    kind=kind.value,
                    payload=payload,
                    status=PendingActionStatus.PENDING.value,
                )
            )
        return self.get_pending_action(action_id)  # type: ignore[return-value]

    def get_pending_action(self, action_id: str) -> PendingActionView | None:
        with self._session() as session:
            row = session.get(PendingActionRow, action_id)
            if row is None:
                return None
            return PendingActionView(
                action_id=row.action_id,
                conversation_id=row.conversation_id,
                customer_id=row.customer_id,
                kind=PendingActionKind(row.kind),
                payload=dict(row.payload),
                status=PendingActionStatus(row.status),
                result=dict(row.result) if row.result else None,
            )

    def mark_action_executed(self, action_id: str, result: dict[str, Any]) -> None:
        with self._session.begin() as session:
            row = session.get(PendingActionRow, action_id)
            if row is None:
                raise KeyError(action_id)
            row.status = PendingActionStatus.EXECUTED.value
            row.result = result

    def execute_refund(
        self,
        *,
        order_id: str,
        customer_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with self._session.begin() as session:
            receipt = session.get(ActionReceiptRow, idempotency_key)
            if receipt is not None:
                return dict(receipt.result)

            order = session.get(OrderRow, order_id)
            if order is None or order.customer_id != customer_id:
                raise ValueError("order_not_found")
            if order.refundable_amount <= 0:
                raise ValueError("order_not_refundable")

            if order.refund_status == "requested":
                result = {
                    "order_id": order_id,
                    "refund_status": "already_requested",
                    "amount": order.refundable_amount,
                }
            else:
                order.refund_status = "requested"
                result = {
                    "order_id": order_id,
                    "refund_status": "requested",
                    "amount": order.refundable_amount,
                }

            session.add(
                ActionReceiptRow(
                    idempotency_key=idempotency_key,
                    action_kind=PendingActionKind.REFUND.value,
                    result=result,
                )
            )
            return result

    def execute_return(
        self,
        *,
        order_id: str,
        customer_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with self._session.begin() as session:
            receipt = session.get(ActionReceiptRow, idempotency_key)
            if receipt is not None:
                return dict(receipt.result)

            order = session.get(OrderRow, order_id)
            if order is None or order.customer_id != customer_id:
                raise ValueError("order_not_found")
            if order.status != "delivered":
                raise ValueError("return_not_available")

            order.return_status = "requested"
            result = {"order_id": order_id, "return_status": "requested"}
            session.add(
                ActionReceiptRow(
                    idempotency_key=idempotency_key,
                    action_kind=PendingActionKind.RETURN_REQUEST.value,
                    result=result,
                )
            )
            return result

    @staticmethod
    def _to_order(row: OrderRow) -> OrderView:
        return OrderView(
            order_id=row.order_id,
            customer_id=row.customer_id,
            status=row.status,
            amount=row.amount,
            refundable_amount=row.refundable_amount,
            refund_status=row.refund_status,
            return_status=row.return_status,
        )
