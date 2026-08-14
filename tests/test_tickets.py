import pytest

from app.config import Settings
from app.container import build_container
from app.domain import TicketPriority, TicketStatus


def build_test_container(tmp_path):
    return build_container(Settings(database_url=f"sqlite:///{tmp_path / 'tickets.db'}"))


def test_ticket_assignment_and_resolution_state_machine(tmp_path):
    container = build_test_container(tmp_path)
    ticket = container.tickets.create_handoff(
        customer_id="CUST-001",
        conversation_id="CONV-TICKET",
        reason="complaint",
        priority=TicketPriority.NORMAL,
    )
    assert ticket.status is TicketStatus.OPEN
    assert ticket.assignee_id is None

    assigned = container.tickets.assign(
        ticket_id=ticket.ticket_id,
        assignee_id="agent-7",
        actor_id="lead-1",
        trace_id="TRC-ASSIGN",
    )
    assert assigned.status is TicketStatus.ASSIGNED
    assert assigned.assignee_id == "agent-7"

    resolved = container.tickets.transition(
        ticket_id=ticket.ticket_id,
        target=TicketStatus.RESOLVED,
        actor_id="agent-7",
        trace_id="TRC-RESOLVE",
        note="customer issue fixed",
    )
    assert resolved.status is TicketStatus.RESOLVED

    closed = container.tickets.transition(
        ticket_id=ticket.ticket_id,
        target=TicketStatus.CLOSED,
        actor_id="lead-1",
        trace_id="TRC-CLOSE",
        note=None,
    )
    assert closed.status is TicketStatus.CLOSED


def test_ticket_cannot_resolve_before_assignment(tmp_path):
    container = build_test_container(tmp_path)
    ticket = container.tickets.create_handoff(
        customer_id="CUST-001",
        conversation_id="CONV-TICKET-2",
        reason="unknown",
        priority=TicketPriority.LOW,
    )
    with pytest.raises(ValueError, match="invalid_ticket_transition"):
        container.tickets.transition(
            ticket_id=ticket.ticket_id,
            target=TicketStatus.RESOLVED,
            actor_id="agent-1",
            trace_id="TRC-BAD",
            note=None,
        )


def test_closed_ticket_cannot_be_reassigned(tmp_path):
    container = build_test_container(tmp_path)
    ticket = container.tickets.create_handoff(
        customer_id="CUST-001",
        conversation_id="CONV-TICKET-3",
        reason="complaint",
        priority=TicketPriority.NORMAL,
    )
    container.tickets.assign(
        ticket_id=ticket.ticket_id,
        assignee_id="agent-1",
        actor_id="lead",
        trace_id="TRC-1",
    )
    container.tickets.transition(
        ticket_id=ticket.ticket_id,
        target=TicketStatus.RESOLVED,
        actor_id="agent-1",
        trace_id="TRC-2",
        note=None,
    )
    container.tickets.transition(
        ticket_id=ticket.ticket_id,
        target=TicketStatus.CLOSED,
        actor_id="lead",
        trace_id="TRC-3",
        note=None,
    )
    with pytest.raises(ValueError, match="ticket_not_assignable"):
        container.tickets.assign(
            ticket_id=ticket.ticket_id,
            assignee_id="agent-2",
            actor_id="lead",
            trace_id="TRC-4",
        )
