# SupportOps AI

Production-oriented **AI Customer Operations Platform** for e-commerce/SaaS support. The project focuses on engineering boundaries that are usually absent from agent demos: authenticated identity, grounded retrieval, safe side effects, human escalation, durable workflow state, distributed coordination, external-dependency degradation, observability, auditability and measurable evaluation.

## What it demonstrates

- **Bounded LLM authority**: an LLM may classify intent and compose grounded answers; it never authorizes a refund/return mutation.
- **Authenticated customer scope**: HTTP and MCP access derive customer identity from verified principals rather than model/user-controlled `customer_id` arguments.
- **Safe mutations**: refund/return requests create persisted pending actions; explicit authenticated confirmation is required, high-value refunds enter human review, and the action ID is propagated as the idempotency key.
- **Distributed reliability**: PostgreSQL owns durable action state and expiry; Redis coordinates cross-replica action locks, TTL mirrors and fixed-window rate limits.
- **Human operations**: tickets have priority, assignment, SLA deadlines and validated state transitions with durable trace-linked audit records.
- **Hybrid retrieval**: BM25 sparse retrieval + dense adapter + weighted RRF + score-aware reranking + answerability gate.
- **Knowledge lifecycle**: versioned sources become deterministic chunks with stable lineage/content hashes; Qdrant synchronization only re-embeds changed chunks and deletes stale vectors.
- **Visible degradation**: embedding/Qdrant and Redis failures follow explicit fail-open/fail-closed policies rather than being silently swallowed.
- **Observability**: low-cardinality Prometheus metrics plus OpenTelemetry spans cover HTTP, routing, retrieval/embedding, policy, Redis coordination and business-tool execution.
- **Evaluation**: routing/safety, retrieval, stateful business tests, a deterministic local latency regression workload, real Redis integration and real Qdrant lifecycle integration are separate gates.

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

## Observability plane

Business audit and APM are deliberately separate concerns:

```text
Durable audit -> actor / resource / policy / mutation / evidence lineage
OpenTelemetry -> request causality / component timing / dependency failure
Prometheus -> aggregate request / operation / degradation rates and latency histograms
```

The API exposes `/metrics` when `METRICS_ENABLED=true`. OpenTelemetry tracing accepts W3C `traceparent`; an OTLP/HTTP trace endpoint can be configured without coupling the application to a specific collector/vendor.

Representative operation spans include `agent.route`, `retrieval.hybrid.search`, `retrieval.dense.search`, `embedding.embed`, `policy.refund`, `policy.return`, `reliability.*` and `tool.*`. Qdrant startup synchronization is separately instrumented as `retrieval.qdrant.startup_sync`.

Prometheus labels are intentionally bounded. Route template, component, operation, backend, outcome, status class and typed degradation reason are metrics dimensions. **Customer/order/action/ticket/trace IDs and arbitrary message/model text are not Prometheus labels.** High-cardinality identifiers remain in traces or durable audit records instead.

Example tracing configuration:

```text
METRICS_ENABLED=true
TRACING_ENABLED=true
OTEL_SERVICE_NAME=supportops-ai
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces
```

The repository does not bundle a Prometheus server, Grafana or an OpenTelemetry Collector. See `docs/OBSERVABILITY.md` for the metric contract, PromQL examples and interpretation limits.

## Distributed mutation reliability

The reliability model deliberately separates durable business state from distributed coordination:

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

If Redis coordination is unavailable during a mutation and fail-closed mode is enabled, confirmation returns a service error before the side effect. Rate-limit backend failure is independently configurable and defaults to fail-open so an unavailable limiter does not take down read/support traffic. Rate-limit violations return HTTP `429` with `Retry-After`.

**This is not an exactly-once claim.** The current Redis lock uses a fixed lease without heartbeat/renewal. The lock reduces overlapping resolution across replicas; the durable receipt/idempotency key remains the retry-safety boundary, and an external payment/refund provider must honor idempotency as well. See `docs/RELIABILITY.md`.

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
python -m evals.run_slo_smoke

RUN_REDIS_INTEGRATION=1 pytest -q -m integration tests/integration/test_redis_integration.py
pip install -e ".[rag]"
RUN_QDRANT_INTEGRATION=1 pytest -q -m integration tests/integration/test_qdrant_integration.py

docker build -t supportops-ai:ci .
```

### Latest verified v0.6 code baseline

The verified code run on head `046955bc6b1112a2caeee09251b79d6dc0c59fe4` completed the full GitHub Actions job successfully:

- Ruff / compile / default + `rag` Compose: passed
- PostgreSQL 17 Alembic migration contract through revision `20260814_0002`: passed; `alembic check` reports no drift
- regular pytest: **46 passed, 2 skipped**
- application coverage: **81.45%** under a 75% gate
- routing/safety benchmark: **140 cases**; routing accuracy / macro-F1 **1.0 / 1.0**; injection block / PII redaction / mutation-policy accuracy **1.0 / 1.0 / 1.0**; unsafe mutations **0**
- retrieval benchmark: **60 cases**; Recall@1 / Recall@3 / MRR@3 **1.0 / 1.0 / 1.0**; citation presence / unsupported abstention **1.0 / 1.0**
- local observability workload: **60 requests**, success rate **1.0**, errors **0**, degraded responses **0**
- local HTTP P50 / P95: **5.652 ms / 8.508 ms**; knowledge P95 **8.924 ms**; order P95 **6.745 ms**
- real Redis reliability integration: **1 passed**
- real Qdrant lifecycle integration: **2 passed**
- Docker image build with `supportops-ai==0.6.0`: passed

The latency workload uses FastAPI TestClient + SQLite + deterministic local retrieval on a GitHub Actions runner. It is a **local regression signal only**, not a production latency SLO, networked PostgreSQL/Redis/Qdrant benchmark, or external LLM/embedding-provider measurement.

The Redis integration uses a real standalone Redis 7.4 service and the Qdrant integration uses a real Qdrant v1.18.2 service, but neither establishes cluster HA.

All benchmark numbers are curated regression/integration metrics. They must not be presented as real-world support accuracy, arbitrary-attack security efficacy, exactly-once delivery, Redis/Qdrant HA, external embedding semantic quality, or production latency/cost.

## Engineering roadmap

Completed through v0.6: authenticated/RBAC boundaries, guarded mutation confirmation, ticket/SLA/audit workflow, Alembic/PostgreSQL release path, hybrid RAG + incremental Qdrant lifecycle, typed retrieval degradation, durable confirmation expiry, Redis cross-replica mutation coordination/rate limiting, and low-cardinality Prometheus + OpenTelemetry instrumentation with a deterministic local latency regression gate.

The next highest-value milestone is **held-out end-to-end conversation/tool evaluation**, not another Agent layer: tool-selection and argument accuracy, task completion, escalation recall, hallucinated-action rate, multi-turn mutation safety and claim-level citation faithfulness. Production SLO thresholds should only be set after deployment traffic is scraped/exported through an external Prometheus/OTel stack. Redis lease renewal/outbox and HA testing should be driven by observed mutation duration/deployment topology rather than added speculatively.

## Provenance

This is a new implementation, not a renamed upstream repository. `docs/UPSTREAM.md` records open-source product/architecture references and licensing notes.
