# SupportOps AI

Production-oriented **AI Customer Operations Platform** for e-commerce/SaaS support. The project focuses on engineering boundaries that are usually absent from agent demos: authenticated identity, grounded retrieval, safe side effects, human escalation, durable workflow state, distributed coordination, external-dependency degradation, auditability and measurable evaluation.

## What it demonstrates

- **Bounded LLM authority**: an LLM may classify intent and compose grounded answers; it never authorizes a refund/return mutation.
- **Authenticated customer scope**: HTTP and MCP access derive customer identity from verified principals rather than model/user-controlled `customer_id` arguments.
- **Safe mutations**: refund/return requests create persisted pending actions; explicit authenticated confirmation is required, high-value refunds enter human review, and the action ID is propagated as the idempotency key.
- **Distributed reliability**: PostgreSQL owns durable action state and expiry; Redis coordinates cross-replica action locks, TTL mirrors and fixed-window rate limits.
- **Human operations**: tickets have priority, assignment, SLA deadlines and validated state transitions with trace-linked audit records.
- **Hybrid retrieval**: BM25 sparse retrieval + dense adapter + weighted RRF + score-aware reranking + answerability gate.
- **Knowledge lifecycle**: versioned sources become deterministic chunks with stable lineage/content hashes; Qdrant synchronization only re-embeds changed chunks and deletes stale vectors.
- **Visible degradation**: embedding/Qdrant and Redis failures follow explicit fail-open/fail-closed policies rather than being silently swallowed.
- **Evaluation**: routing/safety, retrieval, stateful business tests, real Redis integration and real Qdrant lifecycle integration are separate gates.

## Core workflow

```text
Authenticated customer
        |
        v
Input Guardrails ---> injection block / PII redaction
        |
        v
Intent Router ------> optional LLM + deterministic fallback
        |
        v
Application Orchestrator
   |              |                    |
Knowledge      Read tools          Mutating intent
   |              |                    |
Hybrid RAG    customer scope          Policy
   |                                   |
Evidence                      +---------+---------+
   |                          |                   |
Answerability           confirmation        human review
   |                          |                   |
answer/abstain        durable pending action   ticket/SLA
                              |
                      authenticated confirm
                              |
                      Redis action lock
                              |
                      re-read DB + expiry
                              |
                   idempotency-keyed execute
                              |
                       audit + terminal state
```

## Distributed mutation reliability

The v0.5 reliability model deliberately separates durable business state from distributed coordination:

```text
PostgreSQL = source of truth
  pending action status
  created_at / expires_at
  action receipt / idempotency key
  order/ticket/audit state

Redis = coordination/control plane
  action-scoped lease lock
  confirmation TTL mirror
  principal-scoped fixed-window rate limits
```

A confirmation does not trust the state read before locking. The handler acquires an action-scoped lock, **re-reads the pending action inside the lock**, checks durable `expires_at`, then executes the mutation with `action_id` as its idempotency key. Executed/cancelled/expired actions are terminal and retries return the persisted result/state rather than preparing a second mutation.

Default deployment behavior:

```text
RELIABILITY_BACKEND=redis
RELIABILITY_FAIL_CLOSED_MUTATIONS=true
ACTION_CONFIRMATION_TTL_SECONDS=600
ACTION_LOCK_TTL_SECONDS=15
RATE_LIMIT_WINDOW_SECONDS=60
SUPPORT_MESSAGE_RATE_LIMIT=30
ACTION_CONFIRMATION_RATE_LIMIT=10
RATE_LIMIT_FAIL_OPEN=true
```

If Redis coordination is unavailable during a mutation and fail-closed mode is enabled, confirmation returns a service error before the side effect. Rate-limit backend failure is independently configurable and defaults to fail-open so an unavailable limiter does not take down read/support traffic.

Rate-limit violations return HTTP `429` with `Retry-After`. See `docs/RELIABILITY.md` for state ownership, failure semantics and limitations.

**This is not an exactly-once claim.** The current Redis lock uses a fixed lease without heartbeat/renewal. The lock reduces overlapping resolution across replicas; the durable receipt/idempotency key remains the retry-safety boundary, and an external payment/refund provider must honor idempotency as well.

## Knowledge lifecycle and retrieval

The bundled knowledge source contains versioned records with `document_id`, `version`, `title`, `text` and `source_uri`. A deterministic chunker produces stable chunk IDs such as `KB-REFUND-01:1:0000` plus SHA-256 content hashes. Citations expose document/version/chunk/source lineage and audit events retain the evidence version used by the answer.

The bundled JSON is a **versioned source artifact**, not an admin CMS or publication service.

Local/CI retrieval is self-contained:

```text
KNOWLEDGE_BACKEND=local
EMBEDDING_BACKEND=deterministic
```

The deterministic hash vector is a reproducible test representation, **not a semantic embedding model**.

Production-capable dense configuration:

```text
KNOWLEDGE_BACKEND=qdrant
EMBEDDING_BACKEND=openai
EMBEDDING_BASE_URL=https://your-embedding-endpoint/v1
EMBEDDING_MODEL=your-embedding-model
EMBEDDING_DIMENSION=<provider dimension>
QDRANT_URL=http://qdrant:6333
```

Qdrant stores the dense leg only; BM25 remains application-side sparse retrieval. Startup sync embeds/upserts only new/changed chunks and deletes stale remote vectors. Typed dense failures may degrade to BM25 when explicitly allowed, without lowering the answerability threshold.

## Customer API example

Development auth is explicit and local-only:

```bash
curl -X POST http://localhost:8000/v1/support/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Principal-Id: user-1' \
  -H 'X-Customer-Id: CUST-001' \
  -H 'X-Roles: customer' \
  -d '{"conversation_id":"CONV-001","message":"我要退款 ORD-1001"}'
```

A refund response can contain `pending_action_id` and `pending_action_expires_at`; no refund has happened yet. Confirm explicitly:

```bash
curl -X POST http://localhost:8000/v1/actions/ACT-.../confirm \
  -H 'Content-Type: application/json' \
  -H 'X-Principal-Id: user-1' \
  -H 'X-Customer-Id: CUST-001' \
  -H 'X-Roles: customer' \
  -d '{"confirm":true}'
```

`{"confirm": false}` cancels the pending action without a business mutation. An expired action returns terminal `expired` state and cannot execute.

## Human-agent and MCP boundaries

Agent workspace endpoints include ticket listing, assignment, state transitions and trace-audit lookup. MCP v2 exposes bounded search/read/refund-request tools; tools do not accept `customer_id`, and there is deliberately no final refund-confirmation/execution MCP tool.

## Run locally

Single-process local reliability:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

PostgreSQL + Redis deployment path:

```bash
docker compose up --build
```

Optional Qdrant dense service:

```bash
pip install -e ".[dev,rag]"
docker compose --profile rag up -d qdrant
```

## Authentication modes

Development:

```text
AUTH_MODE=dev
```

JWT/OIDC-compatible resource-server mode:

```text
AUTH_MODE=jwt
AUTH_ISSUER=https://idp.example.com/
AUTH_AUDIENCE=supportops-api
AUTH_JWKS_URL=https://idp.example.com/.well-known/jwks.json
AUTH_ALGORITHM=RS256
```

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

RUN_REDIS_INTEGRATION=1 pytest -q -m integration tests/integration/test_redis_integration.py
pip install -e ".[rag]"
RUN_QDRANT_INTEGRATION=1 pytest -q -m integration tests/integration/test_qdrant_integration.py

docker build -t supportops-ai:ci .
```

### Latest verified v0.5 baseline

The verified code run on head `b69cefe14cac2306bf3bcc5f8efc11e80af833d7` completed the full GitHub Actions job successfully:

- Ruff / compile / default + `rag` Compose: passed
- PostgreSQL 17 Alembic migration contract through revision `20260814_0002`: passed; `alembic check` reports no drift
- regular pytest: **42 passed, 2 skipped**
- application coverage: **79.17%** under a 75% gate
- routing/safety benchmark: **140 cases**
- routing accuracy / macro-F1: **1.0 / 1.0**
- prompt-injection block recall / PII redaction recall / mutation-policy accuracy: **1.0 / 1.0 / 1.0**
- unsafe mutation count: **0**
- retrieval benchmark: **60 cases** — 50 supported + 10 unsupported
- Recall@1 / Recall@3 / MRR@3: **1.0 / 1.0 / 1.0**
- citation presence / unsupported abstention recall: **1.0 / 1.0**
- real Redis reliability integration: **1 passed**
- real Qdrant lifecycle integration: **2 passed**
- Docker image build with `supportops-ai==0.5.0`: passed

The Redis integration uses a real standalone Redis 7.4 service and verifies cross-coordinator lock exclusion/release, TTL storage and a shared atomic fixed-window rate counter. It is **not a Redis Sentinel/Cluster/HA test**.

These numbers are curated deterministic regression/integration metrics, not estimates of real-world support accuracy, security efficacy, exactly-once delivery, Redis/Qdrant HA, external embedding semantic quality or production latency/cost.

## Engineering roadmap

Completed through v0.5: authenticated/RBAC boundaries, guarded mutation confirmation, ticket/SLA/audit workflow, Alembic/PostgreSQL release path, hybrid RAG + incremental Qdrant lifecycle, typed retrieval degradation, durable confirmation expiry, Redis cross-replica mutation coordination and rate limiting, and separate safety/retrieval/Redis/Qdrant CI gates.

Next high-value work is **observability rather than more agent complexity**: OpenTelemetry/Prometheus spans and metrics around route/retrieval/tool/policy/Redis/Qdrant operations, followed by reproducible P50/P95 latency and error/degradation SLO reporting. Larger held-out end-to-end conversation evaluation should follow before learned planners/rerankers are considered.

## Provenance

This is a new implementation, not a renamed upstream repository. `docs/UPSTREAM.md` records open-source product/architecture references and licensing notes.
