from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.domain import (
    AuditEventView,
    OrderView,
    PendingActionKind,
    PendingActionStatus,
    PendingActionView,
    TicketPriority,
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
    status: Mapped[str] = mapped_column(String(32), default=TicketStatus.OPEN.value, index=True)
    priority: Mapped[str] = mapped_column(
        String(32),
        default=TicketPriority.NORMAL.value,
        index=True,
    )
    assignee_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TicketEventRow(Base):
    __tablename__ = "ticket_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), index=True)
    from_status: Mapped[str] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), index=True)
    operation: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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

    def create_ticket(
        self,
        customer_id: str,
        conversation_id: str,
        reason: str,
        *,
        priority: TicketPriority,
        sla_due_at: datetime,
    ) -> TicketView:
        ticket_id = f"TKT-{uuid4().hex[:12].upper()}"
        now = datetime.now(UTC)
        with self._session.begin() as session:
            row = TicketRow(
                ticket_id=ticket_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                reason=reason,
                status=TicketStatus.OPEN.value,
                priority=priority.value,
                sla_due_at=sla_due_at,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        ticket = self.get_ticket(ticket_id)
        if ticket is None:
            raise RuntimeError("ticket_create_failed")
        return ticket

    def get_ticket(self, ticket_id: str) -> TicketView | None:
        with self._session() as session:
            row = session.get(TicketRow, ticket_id)
            return self._to_ticket(row) if row else None

    def list_tickets(self, status: TicketStatus | None = None) -> list[TicketView]:
        with self._session() as session:
            statement = select(TicketRow).order_by(TicketRow.created_at.desc())
            if status is not None:
                statement = statement.where(TicketRow.status == status.value)
            return [self._to_ticket(row) for row in session.scalars(statement).all()]

    def assign_ticket(self, ticket_id: str, assignee_id: str, actor_id: str) -> TicketView:
        now = datetime.now(UTC)
        with self._session.begin() as session:
            row = session.get(TicketRow, ticket_id)
            if row is None:
                raise KeyError(ticket_id)
            previous = row.status
            row.assignee_id = assignee_id
            row.status = TicketStatus.ASSIGNED.value
            row.updated_at = now
            session.add(
                TicketEventRow(
                    event_id=f"TEV-{uuid4().hex[:12].upper()}",
                    ticket_id=ticket_id,
                    actor_id=actor_id,
                    from_status=previous,
                    to_status=TicketStatus.ASSIGNED.value,
                    note=f"assigned_to:{assignee_id}",
                    created_at=now,
                )
            )
        ticket = self.get_ticket(ticket_id)
        if ticket is None:
            raise RuntimeError("ticket_assignment_failed")
        return ticket

    def transition_ticket(
        self,
        ticket_id: str,
        target: TicketStatus,
        actor_id: str,
        note: str | None,
    ) -> TicketView:
        now = datetime.now(UTC)
        with self._session.begin() as session:
            row = session.get(TicketRow, ticket_id)
            if row is None:
                raise KeyError(ticket_id)
            previous = row.status
            row.status = target.value
            row.updated_at = now
            session.add(
                TicketEventRow(
                    event_id=f"TEV-{uuid4().hex[:12].upper()}",
                    ticket_id=ticket_id,
                    actor_id=actor_id,
                    from_status=previous,
                    to_status=target.value,
                    note=note,
                    created_at=now,
                )
            )
        ticket = self.get_ticket(ticket_id)
        if ticket is None:
            raise RuntimeError("ticket_transition_failed")
        return ticket

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
        pending = self.get_pending_action(action_id)
        if pending is None:
            raise RuntimeError("pending_action_create_failed")
        return pending

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

    def mark_action_cancelled(self, action_id: str) -> None:
        with self._session.begin() as session:
            row = session.get(PendingActionRow, action_id)
            if row is None:
                raise KeyError(action_id)
            row.status = PendingActionStatus.CANCELLED.value
            row.result = {"cancelled": True}

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

    def record_audit(
        self,
        *,
        trace_id: str,
        actor_id: str,
        operation: str,
        resource_type: str,
        resource_id: str | None,
        outcome: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEventView:
        row = AuditEventRow(
            event_id=f"AUD-{uuid4().hex[:12].upper()}",
            trace_id=trace_id,
            actor_id=actor_id,
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            details=details or {},
            created_at=datetime.now(UTC),
        )
        with self._session.begin() as session:
            session.add(row)
        return self._to_audit(row)

    def get_trace_audit(self, trace_id: str) -> list[AuditEventView]:
        with self._session() as session:
            statement = (
                select(AuditEventRow)
                .where(AuditEventRow.trace_id == trace_id)
                .order_by(AuditEventRow.created_at.asc())
            )
            return [self._to_audit(row) for row in session.scalars(statement).all()]

    @staticmethod
    def sla_due(priority: TicketPriority) -> datetime:
        durations = {
            TicketPriority.URGENT: timedelta(minutes=30),
            TicketPriority.HIGH: timedelta(hours=2),
            TicketPriority.NORMAL: timedelta(hours=8),
            TicketPriority.LOW: timedelta(hours=24),
        }
        return datetime.now(UTC) + durations[priority]

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @classmethod
    def _to_ticket(cls, row: TicketRow) -> TicketView:
        due = cls._ensure_utc(row.sla_due_at)
        created = cls._ensure_utc(row.created_at)
        updated = cls._ensure_utc(row.updated_at)
        status = TicketStatus(row.status)
        return TicketView(
            ticket_id=row.ticket_id,
            customer_id=row.customer_id,
            conversation_id=row.conversation_id,
            reason=row.reason,
            status=status,
            priority=TicketPriority(row.priority),
            assignee_id=row.assignee_id,
            sla_due_at=due,
            sla_breached=(
                status not in {TicketStatus.RESOLVED, TicketStatus.CLOSED}
                and due < datetime.now(UTC)
            ),
            created_at=created,
            updated_at=updated,
        )

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

    @classmethod
    def _to_audit(cls, row: AuditEventRow) -> AuditEventView:
        return AuditEventView(
            event_id=row.event_id,
            trace_id=row.trace_id,
            actor_id=row.actor_id,
            operation=row.operation,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            outcome=row.outcome,
            details=dict(row.details),
            created_at=cls._ensure_utc(row.created_at),
        )
