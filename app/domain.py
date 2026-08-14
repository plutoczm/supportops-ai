from __future__ import annotations

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


class TicketStatus(StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    PENDING_CUSTOMER = "pending_customer"
    RESOLVED = "resolved"
    CLOSED = "closed"


class SupportRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=128)
    customer_id: str = Field(min_length=1, max_length=128)
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


class PendingActionView(BaseModel):
    action_id: str
    conversation_id: str
    customer_id: str
    kind: PendingActionKind
    payload: dict[str, Any]
    status: PendingActionStatus
    result: dict[str, Any] | None = None


class PolicyDecision(BaseModel):
    action: PolicyAction
    reasons: list[str] = Field(default_factory=list)


class SupportResponse(BaseModel):
    trace_id: str
    intent: Intent
    answer: str
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    pending_action_id: str | None = None
    ticket_id: str | None = None
    handoff: bool = False
    safety_labels: list[str] = Field(default_factory=list)


class ConfirmationRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=128)


class ConfirmationResponse(BaseModel):
    trace_id: str
    action_id: str
    status: PendingActionStatus
    result: dict[str, Any]
