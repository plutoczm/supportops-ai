from __future__ import annotations

from mcp.server import MCPServer

from app.container import build_container

container = build_container()
mcp = MCPServer("SupportOps AI")


@mcp.tool()
def search_support_knowledge(query: str) -> dict[str, object]:
    """Search trusted support policy documents without executing business actions."""
    citations = container.knowledge.search(query)
    return {"results": [item.model_dump() for item in citations]}


@mcp.tool()
def get_order(order_id: str, customer_id: str) -> dict[str, object]:
    """Read one order owned by the supplied customer. Never returns another customer's order."""
    order = container.tools.get_order(order_id=order_id.upper(), customer_id=customer_id)
    if order is None:
        return {"found": False}
    return {"found": True, "order": order.model_dump()}


@mcp.tool()
def request_refund(order_id: str, customer_id: str, conversation_id: str) -> dict[str, object]:
    """Prepare a refund request without executing the refund.

    Customer confirmation remains required through the application API.
    """
    response = container.orchestrator.prepare_refund(
        customer_id=customer_id,
        conversation_id=conversation_id,
        order_id=order_id.upper(),
    )
    return response.model_dump(mode="json")


@mcp.tool()
def get_ticket(ticket_id: str, customer_id: str) -> dict[str, object]:
    """Read a support ticket only when it belongs to the supplied customer."""
    ticket = container.store.get_ticket(ticket_id)
    if ticket is None or ticket.customer_id != customer_id:
        return {"found": False}
    return {"found": True, "ticket": ticket.model_dump(mode="json")}


# Deliberately no `confirm_refund` MCP tool. Mutating confirmation remains an authenticated app API.
