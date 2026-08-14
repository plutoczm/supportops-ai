from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from app.auth import AuthenticationError, AuthorizationError, Principal
from app.container import ServiceContainer, build_container
from app.domain import (
    AuditEventView,
    ConfirmationRequest,
    ConfirmationResponse,
    OrderView,
    SupportRequest,
    SupportResponse,
    TicketAssignRequest,
    TicketStatus,
    TicketTransitionRequest,
    TicketView,
)


def create_app(container: ServiceContainer | None = None) -> FastAPI:
    services = container or build_container()
    app = FastAPI(
        title="SupportOps AI",
        version="0.2.0",
        description="AI customer operations with guarded tools, identity, audit, and human handoff.",
    )

    def principal(
        authorization: Annotated[str | None, Header()] = None,
        x_principal_id: Annotated[str | None, Header()] = None,
        x_customer_id: Annotated[str | None, Header()] = None,
        x_roles: Annotated[str | None, Header()] = None,
    ) -> Principal:
        try:
            return services.auth.authenticate(
                authorization=authorization,
                dev_principal_id=x_principal_id,
                dev_customer_id=x_customer_id,
                dev_roles=x_roles,
            )
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    def customer_principal(current: Annotated[Principal, Depends(principal)]) -> Principal:
        try:
            current.require_customer()
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return current

    def agent_principal(current: Annotated[Principal, Depends(principal)]) -> Principal:
        try:
            current.require_agent()
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return current

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/support/messages", response_model=SupportResponse)
    def handle_support_message(
        request: SupportRequest,
        current: Annotated[Principal, Depends(customer_principal)],
    ) -> SupportResponse:
        return services.orchestrator.handle(request, current)

    @app.post("/v1/actions/{action_id}/confirm", response_model=ConfirmationResponse)
    def confirm_action(
        action_id: str,
        request: ConfirmationRequest,
        current: Annotated[Principal, Depends(customer_principal)],
    ) -> ConfirmationResponse:
        try:
            return services.orchestrator.resolve_action(
                action_id,
                current,
                confirm=request.confirm,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/orders/{order_id}", response_model=OrderView)
    def get_order(
        order_id: str,
        current: Annotated[Principal, Depends(customer_principal)],
    ) -> OrderView:
        customer_id = current.require_customer()
        trace_id = f"TRC-{uuid4().hex[:16]}"
        order = services.tools.get_order(
            order_id=order_id.upper(),
            customer_id=customer_id,
            trace_id=trace_id,
            actor_id=current.subject,
        )
        if order is None:
            raise HTTPException(status_code=404, detail="order_not_found")
        return order

    @app.get("/v1/tickets/{ticket_id}", response_model=TicketView)
    def get_ticket(
        ticket_id: str,
        current: Annotated[Principal, Depends(customer_principal)],
    ) -> TicketView:
        customer_id = current.require_customer()
        ticket = services.store.get_ticket(ticket_id)
        if ticket is None or ticket.customer_id != customer_id:
            raise HTTPException(status_code=404, detail="ticket_not_found")
        return ticket

    @app.get("/v1/agent/tickets", response_model=list[TicketView])
    def list_agent_tickets(
        current: Annotated[Principal, Depends(agent_principal)],
        status: Annotated[TicketStatus | None, Query()] = None,
    ) -> list[TicketView]:
        return services.store.list_tickets(status)

    @app.post("/v1/agent/tickets/{ticket_id}/assign", response_model=TicketView)
    def assign_ticket(
        ticket_id: str,
        request: TicketAssignRequest,
        current: Annotated[Principal, Depends(agent_principal)],
    ) -> TicketView:
        try:
            return services.tickets.assign(
                ticket_id=ticket_id,
                assignee_id=request.assignee_id,
                actor_id=current.subject,
                trace_id=f"TRC-{uuid4().hex[:16]}",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ticket_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/agent/tickets/{ticket_id}/transition", response_model=TicketView)
    def transition_ticket(
        ticket_id: str,
        request: TicketTransitionRequest,
        current: Annotated[Principal, Depends(agent_principal)],
    ) -> TicketView:
        try:
            return services.tickets.transition(
                ticket_id=ticket_id,
                target=request.status,
                actor_id=current.subject,
                trace_id=f"TRC-{uuid4().hex[:16]}",
                note=request.note,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ticket_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/agent/audit/traces/{trace_id}", response_model=list[AuditEventView])
    def get_trace_audit(
        trace_id: str,
        current: Annotated[Principal, Depends(agent_principal)],
    ) -> list[AuditEventView]:
        return services.store.get_trace_audit(trace_id)

    return app


app = create_app()
