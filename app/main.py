from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from app.container import build_container
from app.domain import ConfirmationRequest, ConfirmationResponse, OrderView, SupportRequest, SupportResponse, TicketView

container = build_container()
app = FastAPI(
    title="SupportOps AI",
    version="0.1.0",
    description="AI customer operations with guarded tool execution and human handoff.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/support/messages", response_model=SupportResponse)
def handle_support_message(request: SupportRequest) -> SupportResponse:
    return container.orchestrator.handle(request)


@app.post("/v1/actions/{action_id}/confirm", response_model=ConfirmationResponse)
def confirm_action(action_id: str, request: ConfirmationRequest) -> ConfirmationResponse:
    try:
        return container.orchestrator.confirm(action_id, request.customer_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/orders/{order_id}", response_model=OrderView)
def get_order(order_id: str, customer_id: str = Query(min_length=1)) -> OrderView:
    order = container.tools.get_order(order_id=order_id.upper(), customer_id=customer_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    return order


@app.get("/v1/tickets/{ticket_id}", response_model=TicketView)
def get_ticket(ticket_id: str, customer_id: str = Query(min_length=1)) -> TicketView:
    ticket = container.store.get_ticket(ticket_id)
    if ticket is None or ticket.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="ticket_not_found")
    return ticket
