from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Intent(StrEnum):
    KNOWLEDGE = "knowledge"
    ORDER_STATUS = "order_status"
    REFUND = "refund"
    RETURN_REQUEST = "return_request"
    COMPLAINT = "complaint"
    UNKNOWN = "unknown"


class PolicyAction(StrEnum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    REQUIRE_HUMAN = "require_human"


class PendingActionKind(StrEnum):
    REFUND = "refund"
    RETURN_REQUEST = "return_request"


class PendingActionStatus(StrEnum):
    PENDING = "pending"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TicketStatus(StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    PENDING_CUSTOMER = "pending_customer"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(StrEnum):
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class TicketMessageRole(StrEnum):
    CUSTOMER = "customer"
    ASSISTANT = "assistant"
    AGENT = "agent"


class SupportRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)


class RoutingDecision(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    source: str = "rules"


class GuardrailAssessment(BaseModel):
    blocked: bool
    sanitized_text: str
    labels: list[str] = Field(default_factory=list)
    redactions: list[str] = Field(default_factory=list)


class KnowledgeCitation(BaseModel):
    document_id: str
    title: str
    snippet: str
    score: float = Field(ge=0.0)
    source_uri: str | None = None
    document_version: str | None = None
    chunk_id: str | None = None


class OrderView(BaseModel):
    order_id: str
    customer_id: str
    status: str
    amount: float
    refundable_amount: float
    refund_status: str
    return_status: str


class TicketView(BaseModel):
    ticket_id: str
    customer_id: str
    conversation_id: str
    reason: str
    status: TicketStatus
    priority: TicketPriority
    assignee_id: str | None = None
    sla_due_at: datetime
    sla_breached: bool
    created_at: datetime
    updated_at: datetime


class TicketMessageView(BaseModel):
    message_id: str
    ticket_id: str
    conversation_id: str
    customer_id: str
    sender_role: TicketMessageRole
    sender_id: str
    body: str
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PendingActionView(BaseModel):
    action_id: str
    conversation_id: str
    customer_id: str
    kind: PendingActionKind
    payload: dict[str, Any]
    status: PendingActionStatus
    result: dict[str, Any] | None = None
    created_at: datetime
    expires_at: datetime


class PolicyDecision(BaseModel):
    action: PolicyAction
    reasons: list[str] = Field(default_factory=list)


class SupportResponse(BaseModel):
    trace_id: str
    intent: Intent
    answer: str
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    pending_action_id: str | None = None
    pending_action_expires_at: datetime | None = None
    ticket_id: str | None = None
    handoff: bool = False
    safety_labels: list[str] = Field(default_factory=list)
    retrieval_degraded: bool = False
    retrieval_degradation_reason: str | None = None


class ConfirmationRequest(BaseModel):
    confirm: bool = True


class ConfirmationResponse(BaseModel):
    trace_id: str
    action_id: str
    status: PendingActionStatus
    result: dict[str, Any]


class TicketAssignRequest(BaseModel):
    assignee_id: str = Field(min_length=1, max_length=128)


class TicketTransitionRequest(BaseModel):
    status: TicketStatus
    note: str | None = Field(default=None, max_length=1000)


class TicketMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class AuditEventView(BaseModel):
    event_id: str
    trace_id: str
    actor_id: str
    operation: str
    resource_type: str
    resource_id: str | None
    outcome: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
