# SupportOps AI

Production-oriented **AI Customer Operations Platform** for e-commerce/SaaS support. The project focuses on engineering boundaries that are usually absent from agent demos: authenticated identity, grounded retrieval, safe side effects, human escalation, durable workflow state, distributed coordination, external-dependency degradation, observability, auditability and measurable end-to-end evaluation.

## What it demonstrates

- **Bounded LLM authority**: an LLM may classify intent and compose grounded answers; it never authorizes a refund/return mutation.
- **Authenticated customer scope**: HTTP and MCP access derive customer identity from verified principals rather than model/user-controlled `customer_id` arguments.
- **Safe mutations**: refund/return requests create durable pending actions; explicit authenticated confirmation is required, high-value refunds enter human review, and the action ID is propagated as the idempotency key.
- **Distributed reliability**: PostgreSQL owns durable action state/expiry while Redis coordinates cross-replica locks, TTL mirrors and fixed-window rate limits.
- **Human operations**: tickets have priority, assignment, SLA deadlines and validated state transitions with durable trace-linked audit records.
- **Hybrid retrieval**: BM25 + dense retrieval + weighted RRF + score-aware reranking + answerability gate.
- **Knowledge lifecycle**: versioned sources become deterministic chunks with lineage/content hashes; Qdrant synchronization re-embeds changed chunks only and deletes stale vectors.
- **Visible degradation**: embedding/Qdrant and Redis failures follow explicit typed fail-open/fail-closed policies.
- **Observability**: low-cardinality Prometheus metrics plus OpenTelemetry spans cover HTTP, routing, retrieval/embedding, policy, Redis coordination and business-tool execution.
- **End-to-end evaluation discipline**: stateful request-to-tool workflows are scored from durable audit events and database side effects, with frozen regression-set lifecycle rules instead of repeatedly tuning a so-called holdout.

## Core workflow

```text
Authenticated customer
        |
Input Guardrails ---> injection block / PII redaction
        |
Intent Router ------> optional LLM + deterministic fallback
        |
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

## v0.7 end-to-end evaluation

The v0.7 evaluation layer exercises the assembled FastAPI application with fresh seeded state per scenario. It does **not** infer tool selection from answer wording: `knowledge.search`, `order.get`, `refund.quote`, `refund.execute`, `return.execute` and `ticket.create` are scored from durable audit operations and their resource IDs. Order snapshots separately detect unauthorized side effects.

The suite measures workflow/tool selection, tool/resource arguments, task completion, escalation recall, unnecessary handoff, hallucinated action rate, confirmation/cancellation safety, deterministic citation/evidence consistency and cross-customer isolation.

### Holdout lifecycle

The first v1 execution was performed before changing Router/business behavior based on that suite. It contained **61 scenarios** with zero exact normalized overlap against the existing 140-case routing/safety and 60-case retrieval inputs. First-run results included workflow/tool selection **0.9836**, task completion **0.9836**, citation/evidence consistency **0.95**, and perfect mutation/handoff/isolation safety surfaces. It exposed one shipping-address policy routing miss.

After that result was observed, v1 was treated as **frozen regression data**. An over-broad first Router fix was then caught by the restored original v1 because it regressed a missing-order-id tracking flow.

A separately constructed 60-scenario v2 was run next. Its first execution exposed two new defects: an account-security paraphrase failed evidence retrieval, and a Chinese structural prompt-injection variant reached refund preparation. v2 was therefore immediately reclassified as regression data before implementation fixes were made. The fixes were general rather than benchmark-string-specific: address-policy/tracking disambiguation, compound/login query normalization, and broader structural Chinese instruction-override detection.

Current regression gates keep the **original v1 and v2 inputs unchanged**. The latest green code run reports:

```text
v1 regression: 61 scenarios
  tool selection / task completion / citation consistency: 1.0 / 1.0 / 1.0
  hallucinated actions: 0.0
  confirmation / cancellation / cross-customer safety: 1.0 / 1.0 / 1.0

v2 regression: 60 scenarios
  tool selection / task completion: 0.9833 / 0.9833
  tool arguments: 1.0
  escalation recall: 1.0
  hallucinated actions: 0.0
  confirmation / cancellation safety: 1.0 / 1.0
  citation consistency: 0.95
  cross-customer isolation: 1.0
```

The remaining v2 miss is intentionally retained: `how do tracking details and carrier updates work after dispatch?` is ambiguous between a generic shipping-policy question and the order-status flow. The current deterministic router chooses `order_status`; we do not keep changing rules solely to make a known regression set read 100%.

**These are repository-held deterministic regression metrics, not external blind evaluation or production customer-support accuracy.** Exact normalized non-overlap does not prove semantic independence. Because both v1 and v2 have now been observed, another generalization claim requires a separately prepared/frozen unseen set (or external/human-owned evaluation) before candidate changes are evaluated. See `docs/E2E_EVALUATION.md`.

## Observability and reliability boundaries

Business audit and APM are separate concerns:

```text
PostgreSQL audit -> durable actor/resource/policy/mutation/evidence history
OpenTelemetry    -> request causality, component duration and exceptions
Prometheus       -> aggregate request/operation/degradation metrics
```

Prometheus labels are intentionally bounded; customer/order/action/ticket/trace IDs and arbitrary message/model text are excluded. Redis is a coordination plane, not the business source of truth. Mutation confirmation re-reads PostgreSQL state inside the distributed action lock and uses `action_id` as the idempotency key.

**This repository does not claim exactly-once execution.** The Redis lease has no heartbeat/renewal; an external payment/refund provider must honor the same idempotency key if used in production. The repository also does not claim Redis/Qdrant HA or production latency SLOs.

## Knowledge retrieval boundary

The bundled knowledge source is versioned and deterministically chunked. Local/CI uses a deterministic hash-vector representation for reproducibility; it is **not a semantic embedding model**. Production-capable dense retrieval uses an OpenAI-compatible embedding endpoint plus Qdrant. Qdrant currently stores the dense leg only; BM25 remains application-side.

```text
# local/CI
KNOWLEDGE_BACKEND=local
EMBEDDING_BACKEND=deterministic

# production-capable dense path
KNOWLEDGE_BACKEND=qdrant
EMBEDDING_BACKEND=openai
EMBEDDING_BASE_URL=https://your-embedding-endpoint/v1
EMBEDDING_MODEL=your-embedding-model
EMBEDDING_DIMENSION=<provider dimension>
QDRANT_URL=http://qdrant:6333
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

PostgreSQL + Redis:

```bash
docker compose up --build
```

Optional Qdrant adapter:

```bash
pip install -e ".[dev,rag]"
docker compose --profile rag up -d qdrant
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
python -m evals.run_e2e_regression
python -m evals.run_e2e_regression_v2
python -m evals.run_slo_smoke

RUN_REDIS_INTEGRATION=1 pytest -q -m integration tests/integration/test_redis_integration.py
pip install -e ".[rag]"
RUN_QDRANT_INTEGRATION=1 pytest -q -m integration tests/integration/test_qdrant_integration.py

docker build -t supportops-ai:ci .
```

### Latest verified v0.7 code baseline

GitHub Actions run `31816447593` completed the full pre-release code pipeline successfully:

- regular pytest: **60 passed, 2 skipped**
- application coverage: **81.54%** under a 75% gate
- routing/safety: **140 cases**, routing accuracy/macro-F1 **1.0 / 1.0**, injection block/PII redaction/mutation policy **1.0 / 1.0 / 1.0**, unsafe mutations **0**
- retrieval: **60 cases**, Recall@1/3/MRR@3 **1.0 / 1.0 / 1.0**, citation presence/unsupported abstention **1.0 / 1.0**
- original v1 E2E regression: **61 scenarios**, all reported task/safety surfaces at gate with no failures
- v2 E2E regression: **60 scenarios**, tool selection/task completion **0.9833 / 0.9833**, citation consistency **0.95**, all mutation/handoff/isolation safety gates passed
- local observability workload: **60/60 successful**, zero errors/degradation and local HTTP P95 **6.336 ms** in that CI run
- real standalone Redis integration: **1 passed**
- real Qdrant lifecycle integration: **2 passed**
- PostgreSQL migration through `20260814_0002`: passed with no Alembic drift
- Docker build: passed

The latency workload uses TestClient + SQLite + deterministic local retrieval and is a **catastrophic-regression signal only**, not a production SLO. All benchmark numbers are curated regression/integration metrics rather than production accuracy/security/HA claims.

## Engineering roadmap

Completed through v0.7: authenticated/RBAC boundaries, safe mutation confirmation, ticket/SLA/audit workflow, PostgreSQL/Alembic release path, Hybrid RAG + incremental Qdrant lifecycle, typed degradation, Redis distributed coordination/rate limiting, Prometheus/OpenTelemetry observability, and stateful end-to-end workflow evaluation with explicit dataset lifecycle discipline.

The main SupportOps feature surface is now intentionally near **feature freeze**. High-value follow-up should be evidence-driven: a separately frozen provider-backed/unseen evaluation set, production telemetry-based SLO calibration, or outbox/lease-renewal work only if external mutation latency/topology requires it. Adding more Agent roles is not a priority.

## Provenance

This is a new implementation, not a renamed upstream repository. `docs/UPSTREAM.md` records open-source architecture/product references and licensing notes.
