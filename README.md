# SupportOps AI

Production-oriented **AI Customer Operations Platform** for e-commerce/SaaS support. The project focuses on the part that is usually missing from agent demos: real business state, safe side effects, human escalation, tool authorization, idempotency, and measurable evaluation.

## Why this project exists

A useful support agent must do more than answer FAQ. It must safely connect conversation intent to business workflows such as order lookup, refund/return requests, support tickets, and human review without allowing the LLM to become the authorization layer.

## Current foundation

- FastAPI support API with health, message, order, ticket, and action-confirmation endpoints.
- SQLAlchemy persistence; SQLite by default and PostgreSQL in Docker Compose.
- Optional OpenAI-compatible model for intent classification and grounded answer composition.
- Deterministic fallback router so CI and local demos do not depend on paid APIs.
- Pre-model input guardrails for prompt-injection detection and PII redaction.
- Customer-scoped order/ticket access to avoid cross-user data leakage.
- Knowledge evidence retrieval with citations and a strict grounded-answer prompt when an LLM is configured.
- Refund/return action policy: ordinary mutations require explicit customer confirmation; high-value refunds require human review.
- Persisted pending actions and idempotent execution receipts.
- MCP v2 server exposing safe knowledge/order/ticket tools and `request_refund` without exposing a refund-confirmation tool.
- Offline routing/safety evaluation and GitHub Actions quality gates.

## Core workflow

```text
Customer message
  -> input guardrails
  -> intent classification
  -> knowledge / order read / refund / return / complaint
  -> deterministic action policy
  -> direct safe response OR pending confirmation OR human ticket
  -> authenticated confirmation endpoint
  -> idempotent business side effect
```

### Example: refund

`POST /v1/support/messages`

```json
{
  "conversation_id": "CONV-001",
  "customer_id": "CUST-001",
  "message": "我要退款 ORD-1001"
}
```

The response contains a `pending_action_id`; no refund has happened yet. The customer then explicitly confirms through:

`POST /v1/actions/{action_id}/confirm`

```json
{"customer_id": "CUST-001"}
```

The action ID becomes the idempotency key, so a retry does not create a second refund request.

## MCP boundary

The MCP server uses the current official Python SDK v2 and exposes:

- `search_support_knowledge`
- `get_order`
- `request_refund`
- `get_ticket`

There is deliberately **no `confirm_refund` MCP tool**. An agent may prepare a high-risk action, but the final confirmation remains behind the application API boundary.

Run the MCP server with the official CLI, for example:

```bash
mcp dev app/mcp_server.py
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Demo data includes `CUST-001 / ORD-1001`, `ORD-1002`, and `CUST-002 / ORD-2001`.

For PostgreSQL:

```bash
docker compose up --build
```

## Quality gates

```bash
ruff check .
pytest
python evals/run_evals.py
```

The offline suite measures routing accuracy, injection blocking, escalation behavior, and whether mutating actions ever bypass confirmation/human-review policy.

## Engineering roadmap

1. Hybrid RAG: Qdrant dense + sparse retrieval, reranking, citation precision/recall.
2. AuthN/AuthZ: JWT/OIDC identity instead of the demo customer-id contract.
3. Redis-backed rate limits, action-confirmation TTLs, and distributed idempotency.
4. Full ticket/SLA/assignment state machine and agent workspace.
5. Tool audit events + OpenTelemetry traces, token/cost metrics, latency SLOs.
6. 100+ scenario agent evaluation: tool precision/recall, argument accuracy, groundedness, policy adherence, escalation recall, PII leakage, P95 latency, and token cost.
7. Optional structured multi-agent planner only after it beats the bounded baseline under the same evaluation set.

## Provenance

This is a new implementation, not a renamed upstream repository. See `docs/UPSTREAM.md` for open-source references and licensing/provenance notes.
