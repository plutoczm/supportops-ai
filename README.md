# SupportOps AI

Production-oriented **AI Customer Operations Platform** for e-commerce/SaaS support. The project focuses on the parts usually missing from agent demos: authenticated identity, grounded retrieval, safe side effects, human escalation, SLA workflows, auditable tool execution, versioned database migrations, and measurable evaluation.

## What it demonstrates

- **AI application boundary**: the LLM may classify intent and compose grounded answers; it is never the authorization layer.
- **Authenticated customer scope**: HTTP requests derive customer identity from a verified principal rather than trusting `customer_id` in user-controlled payloads.
- **JWT/OIDC-ready resource-server mode**: issuer, audience, JWKS and a fixed signature algorithm are verified before a principal is created.
- **MCP v2 identity boundary**: Streamable HTTP can validate bearer tokens and tools derive customer scope from the verified MCP access-token context.
- **Safe side effects**: refund/return requests create persisted pending actions. Customers must confirm through the application API; high-value refunds are escalated for human review.
- **Human operations**: tickets have priority, assignee, SLA deadline and a validated status-transition state machine.
- **Auditability**: routes, business-tool calls, policy decisions, action preparation/execution and ticket transitions write durable trace-linked audit events.
- **Database evolution**: Alembic owns the production schema path; CI migrates a clean PostgreSQL database and checks ORM metadata for missing migrations.
- **Hybrid retrieval**: BM25 sparse retrieval + a dense retrieval adapter + weighted RRF + score-aware reranking + an answerability gate. Production can use OpenAI-compatible embeddings with Qdrant dense storage.
- **Evaluation**: separate deterministic routing/safety and retrieval benchmarks prevent one metric from hiding regressions in another subsystem.

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
Hybrid RAG  customer scope      Policy
   |                            |
Evidence/citations      +--------+---------+
   |                    |                  |
Answerability      confirmation       human review
   |                    |                  |
answer/refuse     pending action         ticket/SLA
                        |
               authenticated confirm
                        |
                 idempotent execute
                        |
                   audit events
```

## Retrieval architecture

The retrieval layer intentionally has two operating modes.

### Deterministic local/CI mode

Default configuration:

```text
KNOWLEDGE_BACKEND=local
EMBEDDING_BACKEND=deterministic
```

The local path uses:

```text
query
  |-- BM25 sparse retrieval ------------------|
  |                                            |
  +-- deterministic hashed-vector retrieval --+--> weighted RRF
                                                  --> score-aware reranker
                                                  --> evidence score
                                                  --> answerability gate
                                                  --> citations or abstention
```

The hashed vector is a **reproducible CI/local fallback, not a semantic embedding model**. It exists so pull requests can run without downloading a model or calling a paid endpoint.

### Production Qdrant mode

The production adapter replaces only the dense storage/search leg with real embeddings + Qdrant; BM25 remains an application-side sparse baseline and the same fusion/rerank/answerability contract is retained.

```text
KNOWLEDGE_BACKEND=qdrant
EMBEDDING_BACKEND=openai
EMBEDDING_BASE_URL=https://your-embedding-endpoint/v1
EMBEDDING_MODEL=your-embedding-model
QDRANT_URL=http://qdrant:6333
```

Install the optional adapter locally with:

```bash
pip install -e ".[dev,rag]"
```

The Docker image already installs the `rag` extra. An optional Qdrant service is available through the Compose `rag` profile:

```bash
docker compose --profile rag up -d qdrant
```

Then provide a real embedding endpoint/model and select `KNOWLEDGE_BACKEND=qdrant`. The project deliberately refuses `qdrant + deterministic` configuration so the CI-only hash vector cannot be presented as a production semantic embedding.

The current Qdrant adapter stores **dense vectors only**. Sparse retrieval is BM25 in the application process; this repository does not claim that Qdrant sparse-vector indexing has already been implemented.

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

Tools do **not** accept `customer_id`. In JWT mode, customer scope is derived from the verified access token. There is deliberately no `confirm_refund` tool; final mutation confirmation stays behind the application API.

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

For the PostgreSQL deployment path:

```bash
docker compose up --build
```

The application container runs `alembic upgrade head` before starting the API; production container startup does not rely on ORM `create_all()`.

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
python -m compileall app evals migrations

docker compose config -q
docker compose --profile rag config -q

# Against a configured DATABASE_URL, preferably a clean PostgreSQL database:
alembic upgrade head
alembic current --check-heads
alembic check

pytest --cov=app --cov-report=term-missing --cov-fail-under=75
python -m evals.run_evals
python -m evals.run_retrieval_evals
docker build -t supportops-ai:ci .
```

### Latest verified v0.3 code baseline

The verified Hybrid RAG code run reports:

- Ruff and compile checks: passed
- PostgreSQL 17 migration contract: passed
- pytest: **31 passed**
- application coverage: **81.16%** under a 75% gate
- routing/safety benchmark: **140 cases**
- routing accuracy: **1.0**
- routing macro-F1: **1.0**
- prompt-injection block recall: **1.0** on the curated attack set
- PII redaction recall: **1.0** on the curated PII set
- mutating-action policy accuracy: **1.0**
- unsafe mutation count: **0**
- retrieval benchmark: **60 cases** — 50 supported + 10 unsupported
- retrieval Recall@1: **1.0**
- retrieval Recall@3: **1.0**
- retrieval MRR@3: **1.0**
- grounded-answer citation presence: **1.0**
- unsupported-query abstention recall: **1.0**
- Docker image build: passed

These are **curated deterministic regression metrics**, not estimates of real-world customer-support accuracy, security effectiveness, semantic-retrieval quality, or LLM quality.

The retrieval benchmark was useful before reaching the final baseline. The first hybrid implementation achieved Recall@3 = 1.0 but Recall@1 = 0.92 / MRR@3 = 0.96, exposing a ranking-calibration problem. Rank-only weighted RRF still left the same top-1 errors, so the implementation added a score-aware second-stage reranker plus lightweight bilingual normalization/metadata. The fixed benchmark then passed without weakening the gates.

## Engineering roadmap

Completed in the current v0.3 foundation branch:

- guarded refund/return workflow and idempotent confirmation
- JWT/JWKS principal boundary and customer/agent RBAC
- MCP bearer-token identity boundary for Streamable HTTP
- ticket priority/assignment/SLA/state-machine workflow
- durable tool/policy/ticket audit events with trace IDs and latency metadata
- Alembic schema migrations and PostgreSQL migration CI
- 140-case deterministic routing/safety benchmark
- hybrid retrieval abstraction: BM25 + dense adapter + weighted RRF + score-aware reranking
- OpenAI-compatible embedding adapter + Qdrant dense-vector adapter
- evidence threshold / unsupported-query abstention and source-id citation contract
- 60-case retrieval benchmark with Recall@1/3, MRR@3, citation and abstention gates

Next high-value milestones:

1. Production-grade knowledge ingestion: document versioning, chunk provenance, incremental indexing and stale-index handling.
2. Qdrant integration CI with a deterministic mock embedding endpoint, plus failure/degradation tests for embedding/vector-store outages.
3. Evaluate a learned/cross-encoder reranker only if it improves the same fixed retrieval benchmark without harming latency/cost.
4. Redis-backed rate limits, confirmation TTLs and distributed idempotency locks.
5. OpenTelemetry export plus P95 latency/token/cost SLO reporting.
6. End-to-end conversation evaluation for tool-selection precision/recall, argument accuracy, task completion, escalation and hallucinated-action rate.

## Provenance

This is a new implementation, not a renamed upstream repository. `docs/UPSTREAM.md` records open-source product/architecture references and licensing notes.
