# SupportOps AI

Production-oriented **AI Customer Operations Platform** for e-commerce/SaaS support. The project focuses on the parts usually missing from agent demos: authenticated identity, grounded retrieval, safe side effects, human escalation, SLA workflows, auditable tool execution, versioned data/schema changes, external-dependency degradation, and measurable evaluation.

## What it demonstrates

- **AI application boundary**: an LLM may classify intent and compose grounded answers; it is never the authorization layer.
- **Authenticated customer scope**: HTTP and MCP business access derive customer identity from verified principals rather than model/user-controlled `customer_id` tool arguments.
- **Safe side effects**: refund/return requests create persisted pending actions; explicit authenticated confirmation is required before execution, and high-value refunds enter human review.
- **Human operations**: ticket priority, assignment, SLA deadline and state transitions are validated and audited.
- **Hybrid retrieval**: BM25 sparse retrieval + dense adapter + weighted RRF + score-aware reranking + answerability gate.
- **Knowledge lifecycle**: versioned source documents become deterministic chunks with stable lineage and content hashes; Qdrant synchronization only re-embeds changed chunks and removes stale vectors.
- **Visible degradation**: embedding/Qdrant failures have typed reasons. When configured, dense failure degrades to BM25 without pretending the dense path succeeded; strict mode fails fast.
- **Evaluation**: routing/safety, deterministic retrieval, stateful business tests and real Qdrant lifecycle integration are separate quality gates.

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

## Knowledge lifecycle and retrieval

Knowledge is no longer a Python hard-coded list. The bundled source file contains active documents with:

```text
document_id
version
title
text
source_uri
```

A deterministic chunker produces stable chunk identities such as:

```text
KB-REFUND-01:1:0000
```

Every chunk also has a SHA-256 content hash. Citations expose `document_id`, `document_version`, `chunk_id` and `source_uri`, and knowledge-search audit events retain the retrieved chunk/version lineage.

The current bundled JSON is a **versioned source artifact**, not an admin-facing document-management service. External ingestion, approval/version publication and object-store connectors remain future work.

### Deterministic local/CI mode

```text
KNOWLEDGE_BACKEND=local
EMBEDDING_BACKEND=deterministic
```

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

The hashed vector is a **reproducible test/local representation, not a semantic embedding model**. It keeps pull-request evaluation deterministic and network-independent.

### Production-capable dense path

```text
KNOWLEDGE_BACKEND=qdrant
EMBEDDING_BACKEND=openai
EMBEDDING_BASE_URL=https://your-embedding-endpoint/v1
EMBEDDING_MODEL=your-embedding-model
EMBEDDING_DIMENSION=<provider dimension>
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=supportops_knowledge
```

The Qdrant adapter stores the **dense leg only**; sparse retrieval remains application-side BM25. `qdrant + deterministic` is rejected so the CI-only representation cannot be presented as production semantic retrieval.

On startup, Qdrant synchronization compares stable `index_id + content_hash` metadata:

- new collection -> embed/upsert all desired chunks;
- unchanged chunk -> no re-embedding or upsert;
- changed content -> embed/upsert only the changed chunk;
- removed source/chunk -> delete the stale remote vector.

The sync result records desired, embedded, upserted, deleted and unchanged chunk counts.

### Failure/degradation contract

External retrieval failures are typed, including embedding timeout/rate-limit/provider/invalid-response and Qdrant index/search failures.

```text
RETRIEVAL_ALLOW_SPARSE_FALLBACK=true
```

With fallback enabled, a typed dense-backend failure keeps BM25 available and marks the response/audit trail with `retrieval_degraded=true` plus a degradation reason. With fallback disabled, the same startup/search failure propagates and the application fails fast instead of silently changing behavior.

This fallback preserves availability, **not semantic equivalence**. A sparse-only degraded response must not be reported as successful dense retrieval.

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

A refund response can contain a `pending_action_id`; no refund has happened yet. Confirm it explicitly:

```bash
curl -X POST http://localhost:8000/v1/actions/ACT-.../confirm \
  -H 'Content-Type: application/json' \
  -H 'X-Principal-Id: user-1' \
  -H 'X-Customer-Id: CUST-001' \
  -H 'X-Roles: customer' \
  -d '{"confirm":true}'
```

The action ID is also the idempotency key. `{"confirm": false}` cancels the pending action without a business mutation.

## Human-agent workspace

A `support_agent` or `support_admin` principal can use:

- `GET /v1/agent/tickets`
- `POST /v1/agent/tickets/{ticket_id}/assign`
- `POST /v1/agent/tickets/{ticket_id}/transition`
- `GET /v1/agent/audit/traces/{trace_id}`

Ticket transitions are validated rather than directly writing status. SLA targets in this foundation are deterministic by priority: urgent 30 minutes, high 2 hours, normal 8 hours, low 24 hours.

## MCP boundary

The official MCP Python SDK v2 server exposes a bounded surface:

- `search_support_knowledge(query)`
- `get_order(order_id)`
- `request_refund(order_id, conversation_id)`
- `get_ticket(ticket_id)`

Tools do **not** accept `customer_id`. In JWT mode, customer scope comes from the verified access token. There is deliberately no refund-confirmation/execution MCP tool; final mutation confirmation remains behind the application API.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

PostgreSQL deployment path:

```bash
docker compose up --build
```

Optional Qdrant service:

```bash
pip install -e ".[dev,rag]"
docker compose --profile rag up -d qdrant
```

The Docker image installs the `rag` extra. The Compose profile pins the Qdrant **server** image independently from the Python client version range; server/client versions are separate compatibility surfaces.

## Authentication modes

Development:

```text
AUTH_MODE=dev
```

Production resource-server mode:

```text
AUTH_MODE=jwt
AUTH_ISSUER=https://idp.example.com/
AUTH_AUDIENCE=supportops-api
AUTH_JWKS_URL=https://idp.example.com/.well-known/jwks.json
AUTH_ALGORITHM=RS256
```

The application validates JWT signature, issuer, audience, required temporal claims and subject before deriving customer/role claims. The identity provider remains responsible for login and token issuance.

## Quality gates

```bash
ruff check .
python -m compileall app evals migrations tests/integration

docker compose config -q
docker compose --profile rag config -q

alembic upgrade head
alembic current --check-heads
alembic check

pytest --cov=app --cov-report=term-missing --cov-fail-under=75
python -m evals.run_evals
python -m evals.run_retrieval_evals

pip install -e ".[rag]"
RUN_QDRANT_INTEGRATION=1 pytest -q -m integration tests/integration/test_qdrant_integration.py

docker build -t supportops-ai:ci .
```

### Latest verified v0.4 baseline

The current PR head has a complete green GitHub Actions run:

- Ruff / compile: passed
- default + `rag` Compose config: passed
- PostgreSQL 17 Alembic migration contract: passed
- regular pytest: **37 passed, 1 skipped**
- application coverage: **80.08%** under a 75% gate
- routing/safety benchmark: **140 cases**
- routing accuracy / macro-F1: **1.0 / 1.0**
- prompt-injection block recall: **1.0**
- PII redaction recall: **1.0**
- mutation-policy accuracy: **1.0**
- unsafe mutation count: **0**
- retrieval benchmark: **60 cases** — 50 supported + 10 unsupported
- Recall@1 / Recall@3 / MRR@3: **1.0 / 1.0 / 1.0**
- grounded-answer citation presence: **1.0**
- unsupported-query abstention recall: **1.0**
- real Qdrant lifecycle integration: **2 passed**
- Docker image build with `supportops-ai==0.4.0` and the `rag` extra: passed

The Qdrant integration test runs Qdrant v1.18.2 and a local HTTP server that implements the OpenAI-compatible embedding protocol. The HTTP test embedding uses a deterministic 64-dimensional representation so CI can validate provider protocol, indexing and failure behavior without making a semantic-model-quality claim.

The integration test verifies: first-time collection/upsert, zero re-embedding for unchanged chunks, changed-only upsert, stale-vector deletion, dense query, and typed Qdrant outage behavior. Separate unit tests verify startup failure with sparse fallback enabled and fail-fast behavior when fallback is disabled.

These are **curated deterministic regression and integration metrics**, not estimates of real-world support accuracy, security effectiveness, external embedding quality, Qdrant high availability, or production semantic-retrieval quality.

## Engineering roadmap

Completed through v0.4:

- authenticated customer/MCP boundaries and RBAC
- guarded refund/return confirmation + idempotency
- human ticket/SLA workflow and durable trace-linked audit
- Alembic/PostgreSQL migration CI
- hybrid BM25+dense retrieval, weighted RRF, score-aware reranking and answerability
- versioned knowledge sources, stable chunk provenance and content hashes
- incremental Qdrant dense indexing with stale-vector deletion
- typed embedding/Qdrant failure reasons and explicit sparse-only degradation
- 140-case safety benchmark + 60-case retrieval benchmark + real Qdrant lifecycle CI

Next high-value work:

1. Redis-backed rate limits, confirmation TTLs and distributed idempotency locks.
2. OpenTelemetry/Prometheus export with retrieval/tool spans and P95 latency/token/cost SLO reporting.
3. Larger held-out retrieval and end-to-end conversation sets before making semantic/model quality claims.
4. Claim-level citation precision/faithfulness for multi-document answers.
5. External knowledge publication/approval connectors and object-store/document ingestion.
6. Evaluate a learned reranker or planner only if it beats the bounded baseline under the same quality, latency and policy gates.

## Provenance

This is a new implementation, not a renamed upstream repository. `docs/UPSTREAM.md` records open-source product/architecture references and licensing notes.
