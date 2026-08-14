# SupportOps AI

Production-oriented **AI Customer Operations Platform** for e-commerce/SaaS support. The project focuses on the parts usually missing from agent demos: authenticated identity, real business state, safe side effects, human escalation, SLA workflows, auditable tool execution, and measurable evaluation.

## What it demonstrates

- **AI application boundary**: the LLM classifies intent and composes grounded answers; it is never the authorization layer.
- **Authenticated customer scope**: HTTP requests derive customer identity from a verified principal rather than trusting `customer_id` in user-controlled payloads.
- **JWT/OIDC-ready resource-server mode**: issuer, audience, JWKS and fixed signature algorithm are verified before a principal is created. A strict explicit-header development mode keeps local demos deterministic.
- **MCP v2 identity boundary**: Streamable HTTP can validate bearer tokens and tools derive the customer from the verified MCP access-token context; customer identity is not a tool argument.
- **Safe side effects**: refund/return requests create persisted pending actions. The customer must confirm through the application API; high-value refunds are escalated for human review.
- **Human operations**: tickets have priority, assignee, SLA deadline and a validated status-transition state machine.
- **Auditability**: routes, business-tool calls, policy decisions, action preparation/execution and ticket transitions write durable trace-linked audit events.
- **Evaluation**: a deterministic 140-case routing/safety benchmark measures accuracy, macro-F1, prompt-injection blocking, PII redaction and mutation-policy invariants.

## Core workflow

```text
Authenticated customer
        |
        v
Input Guardrails -----> block injection / redact PII
        |
        v
Intent Router --------> optional LLM + deterministic fallback
        |
        v
Application Orchestrator
   |          |                 |
Knowledge   Read tools       Mutating intent
   |          |                 |
Evidence   customer scope      Policy
                                |
                       +--------+---------+
                       |                  |
                  confirmation       human review
                       |                  |
                pending action         ticket/SLA
                       |
              authenticated confirm
                       |
                idempotent execute
                       |
                  audit events
```

## Customer API example

Development auth is intentionally explicit. No endpoint accepts `customer_id` in the request body as proof of identity.

```bash
curl -X POST http://localhost:8000/v1/support/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Principal-Id: user-1' \
  -H 'X-Customer-Id: CUST-001' \
  -H 'X-Roles: customer' \
  -d '{"conversation_id":"CONV-001","message":"我要退款 ORD-1001"}'
```

The response contains a `pending_action_id`; no refund has happened yet. Confirm it explicitly:

```bash
curl -X POST http://localhost:8000/v1/actions/ACT-.../confirm \
  -H 'Content-Type: application/json' \
  -H 'X-Principal-Id: user-1' \
  -H 'X-Customer-Id: CUST-001' \
  -H 'X-Roles: customer' \
  -d '{"confirm":true}'
```

The action ID is also the idempotency key, so retries do not create a duplicate business side effect. Sending `{"confirm": false}` cancels the pending action without mutating the order.

## Human-agent workspace

A principal with `support_agent` or `support_admin` can use:

- `GET /v1/agent/tickets`
- `POST /v1/agent/tickets/{ticket_id}/assign`
- `POST /v1/agent/tickets/{ticket_id}/transition`
- `GET /v1/agent/audit/traces/{trace_id}`

Ticket transitions are validated rather than directly writing a status field. A typical path is `open -> assigned -> pending_customer/resolved -> closed`.

SLA targets in the foundation are deterministic configuration-by-priority:

- urgent: 30 minutes
- high: 2 hours
- normal: 8 hours
- low: 24 hours

## MCP boundary

The server uses the official MCP Python SDK v2. Its safe tool surface is:

- `search_support_knowledge(query)`
- `get_order(order_id)`
- `request_refund(order_id, conversation_id)`
- `get_ticket(ticket_id)`

Notice that tools do **not** accept `customer_id`. In JWT mode, customer scope is derived from the verified access token. There is deliberately no `confirm_refund` tool; final mutation confirmation stays behind the application API.

For an authenticated Streamable HTTP deployment configure `MCP_AUTH_MODE=jwt` and the issuer/resource settings, then run:

```bash
python -m app.mcp_server
```

For local in-memory/stdio-style testing, authorization is a process boundary rather than an HTTP bearer-token boundary; `MCP_AUTH_MODE=disabled` uses only the explicitly configured demo customer.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Demo orders include `CUST-001 / ORD-1001`, `ORD-1002`, and `CUST-002 / ORD-2001`.

For PostgreSQL:

```bash
docker compose up --build
```

## Authentication modes

### Development

```text
AUTH_MODE=dev
```

Requests must provide an explicit `X-Principal-Id`; customer requests also provide `X-Customer-Id`. These headers are a local-development contract and must not be treated as production authentication.

### JWT/OIDC resource server

```text
AUTH_MODE=jwt
AUTH_ISSUER=https://idp.example.com/
AUTH_AUDIENCE=supportops-api
AUTH_JWKS_URL=https://idp.example.com/.well-known/jwks.json
AUTH_ALGORITHM=RS256
```

The application validates signature, issuer, audience, expiration/issued-at presence and subject before deriving customer/role claims. The identity provider remains responsible for login and token issuance.

## Quality gates

```bash
ruff check .
python -m compileall app evals
pytest --cov=app --cov-report=term-missing --cov-fail-under=75
python evals/run_evals.py
docker build -t supportops-ai:ci .
```

The benchmark is a curated deterministic regression suite, not a claim of real-world production accuracy. See `docs/EVALUATION.md`.

## Engineering roadmap

Completed in the current foundation branch:

- guarded refund/return workflow and idempotent confirmation
- JWT/JWKS principal boundary and customer/agent RBAC
- MCP bearer-token identity boundary for Streamable HTTP
- ticket priority/assignment/SLA/state-machine workflow
- durable tool/policy/ticket audit events with trace IDs and latency metadata
- 140-case deterministic routing/safety benchmark

Next high-value milestones:

1. Alembic schema migrations and migration CI against PostgreSQL.
2. Hybrid RAG: Qdrant dense+sparse retrieval, reranking and citation precision/recall evaluation.
3. Redis-backed rate limits, confirmation TTLs and distributed idempotency locks.
4. OpenTelemetry export plus P95 latency/token/cost SLO reporting.
5. Tool-selection/argument evaluation over end-to-end conversations, plus groundedness and citation-quality evaluation.
6. Optional structured planner only after it beats the bounded baseline under the same business-policy gates.

## Provenance

This is a new implementation, not a renamed upstream repository. `docs/UPSTREAM.md` records open-source product/architecture references and licensing notes.
