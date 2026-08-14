from __future__ import annotations

from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response

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
from app.reliability import MutationLockBusy, ReliabilityBackendError


def get_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_principal_id: Annotated[str | None, Header()] = None,
    x_customer_id: Annotated[str | None, Header()] = None,
    x_roles: Annotated[str | None, Header()] = None,
) -> Principal:
    services: ServiceContainer = request.app.state.services
    try:
        return services.auth.authenticate(
            authorization=authorization,
            dev_principal_id=x_principal_id,
            dev_customer_id=x_customer_id,
            dev_roles=x_roles,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def get_customer_principal(
    current: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    try:
        current.require_customer()
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return current


def get_agent_principal(
    current: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    try:
        current.require_agent()
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return current


def _enforce_rate_limit(
    services: ServiceContainer,
    *,
    current: Principal,
    scope: str,
    limit: int,
) -> None:
    try:
        decision = services.reliability.check_rate_limit(
            scope=scope,
            subject=current.subject,
            limit=limit,
            window_seconds=services.settings.rate_limit_window_seconds,
        )
    except ReliabilityBackendError as exc:
        if services.settings.rate_limit_fail_open:
            return
        raise HTTPException(status_code=503, detail=exc.reason) from exc
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail="rate_limit_exceeded",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


def create_app(container: ServiceContainer | None = None) -> FastAPI:
    services = container or build_container()
    app = FastAPI(
        title="SupportOps AI",
        version="0.6.0",
        description=(
            "AI customer operations with guarded tools, identity, audit, distributed "
            "reliability, observability and human handoff."
        ),
    )
    app.state.services = services
    app.add_event_handler("shutdown", services.observability.shutdown)

    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        started = perf_counter()
        status_code = 500
        route = "unmatched"
        parent_context = services.observability.extract_context(request.headers)
        try:
            with services.observability.operation(
                "http.server.request",
                component="http",
                backend="fastapi",
                context=parent_context,
            ) as observation:
                observation.set_attribute("http.request.method", request.method)
                response = await call_next(request)
                status_code = response.status_code
                route_object = request.scope.get("route")
                route = str(getattr(route_object, "path", "unmatched"))
                observation.set_attribute("http.route", route)
                observation.set_attribute("http.response.status_code", status_code)
                if status_code >= 500:
                    observation.set_outcome("server_error")
                elif status_code >= 400:
                    observation.set_outcome("client_error")
                return response
        finally:
            route_object = request.scope.get("route")
            route = str(getattr(route_object, "path", route))
            services.observability.record_http(
                method=request.method,
                route=route,
                status_code=status_code,
                duration_seconds=perf_counter() - started,
            )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "reliability_backend": services.reliability.backend_name,
            "metrics": "enabled" if services.settings.metrics_enabled else "disabled",
            "tracing": "enabled" if services.settings.tracing_enabled else "disabled",
        }

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        if not services.settings.metrics_enabled:
            raise HTTPException(status_code=404, detail="metrics_disabled")
        return Response(
            content=services.observability.render_metrics(),
            media_type=services.observability.metrics_content_type,
        )

    @app.post("/v1/support/messages", response_model=SupportResponse)
    def handle_support_message(
        request: SupportRequest,
        current: Annotated[Principal, Depends(get_customer_principal)],
    ) -> SupportResponse:
        _enforce_rate_limit(
            services,
            current=current,
            scope="support-message",
            limit=services.settings.support_message_rate_limit,
        )
        return services.orchestrator.handle(request, current)

    @app.post("/v1/actions/{action_id}/confirm", response_model=ConfirmationResponse)
    def confirm_action(
        action_id: str,
        request: ConfirmationRequest,
        current: Annotated[Principal, Depends(get_customer_principal)],
    ) -> ConfirmationResponse:
        _enforce_rate_limit(
            services,
            current=current,
            scope="action-confirmation",
            limit=services.settings.action_confirmation_rate_limit,
        )
        try:
            return services.orchestrator.resolve_action(
                action_id,
                current,
                confirm=request.confirm,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except MutationLockBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ReliabilityBackendError as exc:
            raise HTTPException(status_code=503, detail=exc.reason) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/orders/{order_id}", response_model=OrderView)
    def get_order(
        order_id: str,
        current: Annotated[Principal, Depends(get_customer_principal)],
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
        current: Annotated[Principal, Depends(get_customer_principal)],
    ) -> TicketView:
        customer_id = current.require_customer()
        ticket = services.store.get_ticket(ticket_id)
        if ticket is None or ticket.customer_id != customer_id:
            raise HTTPException(status_code=404, detail="ticket_not_found")
        return ticket

    @app.get("/v1/agent/tickets", response_model=list[TicketView])
    def list_agent_tickets(
        current: Annotated[Principal, Depends(get_agent_principal)],
        status: Annotated[TicketStatus | None, Query()] = None,
    ) -> list[TicketView]:
        return services.store.list_tickets(status)

    @app.post("/v1/agent/tickets/{ticket_id}/assign", response_model=TicketView)
    def assign_ticket(
        ticket_id: str,
        request: TicketAssignRequest,
        current: Annotated[Principal, Depends(get_agent_principal)],
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
        current: Annotated[Principal, Depends(get_agent_principal)],
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
        current: Annotated[Principal, Depends(get_agent_principal)],
    ) -> list[AuditEventView]:
        return services.store.get_trace_audit(trace_id)

    return app


app = create_app()
