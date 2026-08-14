# Architecture

## Trust and state model

SupportOps AI treats model output, user-provided identifiers and external adapters as untrusted. Identity, authorization, business policy, confirmation and mutation coordination are application responsibilities.

```text
Identity Provider
      |
verified Principal
      |
Guardrails -> Intent Router
      |
+-----+----------------------+------------------+
|                            |                  |
Knowledge/RAG             read tools        mutation intent
|                            |                  |
answerability             customer scope       policy
                                                |
                                      persisted pending action
                                                |
                                      authenticated confirmation
                                                |
                                      Redis action-scoped lock
                                                |
                                      re-read PostgreSQL state
                                      + expiry + customer scope
                                                |
                                      idempotency-keyed tool
                                                |
                                      receipt / terminal state
                                                |
                                             audit
```

## Durable state vs distributed coordination

The architecture intentionally does **not** make Redis the system of record.

### PostgreSQL owns durable facts

- order/ticket state;
- pending action kind, payload and status;
- `created_at` and durable `expires_at`;
- action receipt keyed by the action/idempotency key;
- audit history.

Alembic revision `20260814_0002` adds the pending-action lifetime fields and indexes `expires_at`. Existing pre-v0.5 pending rows are backfilled to immediate expiry instead of being granted a new unbounded confirmation window.

### Redis owns coordination/control-plane state

- short action-scoped lease lock;
- confirmation TTL mirror;
- principal/scoped fixed-window request counters.

Local development can use an in-process coordinator, but that mode only coordinates one Python process and is not suitable as a multi-replica safety boundary.

## Mutation resolution algorithm

For a pending refund/return confirmation:

```text
read pending action + customer scope
          |
terminal? +---- yes -> return persisted terminal result
          |
acquire action lock (SET NX PX in Redis)
          |
          +---- busy -> 409 resolution in progress
          +---- Redis error + fail-closed -> 503, no mutation
          |
re-read pending action inside lock
          |
terminal? +---- yes -> return persisted terminal result
          |
check durable expires_at
          |
expired?  +---- yes -> persist EXPIRED, no mutation
          |
execute business tool with action_id as idempotency key
          |
persist receipt + terminal action state
          |
release lock only if token still owns the Redis key
```

The second read inside the lock matters: two replicas can both observe `PENDING` before one obtains the lease. The lock prevents both from proceeding from the same stale pre-lock read.

The Redis lock is acquired with a random token and `SET NX PX`; release uses a token-check Lua script so a process cannot delete a lease that expired and was subsequently acquired by another process.

## Exactly-once boundary

The implementation does **not** claim exactly-once execution. The lock lease has a fixed TTL and currently has no heartbeat/renewal. If a downstream mutation exceeds the configured lease, another replica can eventually obtain the lock. Therefore:

- the lease must be longer than the expected synchronous mutation latency;
- `action_id` remains the application idempotency key;
- the local database receipt protects retried local mutations;
- a real external refund/payment provider must also support/receive the same idempotency key;
- lease renewal or a durable job/outbox workflow is the next step if mutations become long-running.

## Confirmation lifetime

`expires_at` is durable PostgreSQL state. Redis stores a TTL mirror for fast coordination/visibility, but Redis restart/key loss does not redefine the business expiry. Confirmation checks always use the database deadline.

An expired pending action transitions to `EXPIRED` and returns a terminal `{expired: true}` result without calling the business mutation tool.

## Rate limiting

Redis uses an atomic Lua-backed **fixed-window** counter. Current API scopes include support messages and action confirmations. Counters are keyed by authenticated principal subject plus scope.

Exceeded limits return HTTP 429 and `Retry-After`. This is intentionally described as fixed-window; it is not a sliding-window or token-bucket implementation.

## Failure policy matrix

| Dependency/operation | Default behavior | Rationale |
|---|---|---|
| Redis startup in Redis deployment mode | fail fast | do not start a replica that cannot provide configured coordination |
| Redis action-lock/TTL refresh before mutation | fail closed | no side effect when cross-replica coordination is unavailable |
| action lock busy | 409 | another resolution may be in flight |
| rate-limit Redis failure | fail open (configurable) | limiter outage should not automatically take down support/read traffic |
| dense retrieval failure | visible BM25 fallback when enabled | availability with explicit degradation; answerability threshold unchanged |
| dense retrieval failure in strict mode | fail fast/propagate | avoid silently changing configured semantics |

Lock-release or TTL-cleanup failures **after** a completed mutation are audited as degraded; they do not roll back a business mutation whose durable receipt/state has already been written.

## Identity and authorization

Production HTTP mode verifies JWT signature, issuer, audience, required temporal claims and subject before creating a principal. Customer identity is derived from validated claims, not payload fields. MCP Streamable HTTP follows the same server-side customer-scope principle and deliberately omits the final mutation-confirmation tool.

## Knowledge lifecycle and retrieval

Versioned bundled knowledge records are deterministically chunked into stable `document_id:version:ordinal` identities with SHA-256 content hashes. Qdrant dense synchronization compares desired chunk hashes against remote payload metadata, embeds/upserts changed chunks only and deletes stale vectors. BM25 stays application-side; weighted RRF, score-aware reranking and the answerability gate remain common to local and Qdrant modes.

The local deterministic vector is a regression representation, not a semantic embedding model. Qdrant integration uses a real service but does not claim cluster HA or external-model semantic quality.

## Human workflow and audit

Tickets maintain priority, assignee, SLA deadline and validated state transitions. Business tools, policy decisions, knowledge degradation, action preparation/expiry/cancellation/execution and ticket transitions emit durable trace-linked audit records.

## Release/CI contract

GitHub Actions starts PostgreSQL 17, standalone Redis 7.4 and Qdrant v1.18.2. It verifies Alembic upgrade/drift, unit/coverage gates, the 140-case safety set, 60-case retrieval set, real Redis reliability integration, real Qdrant lifecycle integration and Docker build.

Current adapter boundaries:

- FastAPI API; JWT/JWKS or explicit dev principal headers;
- SQLAlchemy + PostgreSQL/SQLite; Alembic schema evolution;
- Redis local/standalone coordination adapter;
- MCP Python SDK v2;
- OpenAI-compatible optional LLM and embedding providers;
- BM25 + in-memory/Qdrant dense retrieval;
- versioned bundled JSON knowledge source.

Not yet claimed: Redis Sentinel/Cluster HA, lock renewal, distributed exactly-once execution, external payment-provider idempotency verification, OpenTelemetry/Prometheus SLOs, external knowledge publication workflows or production semantic/model quality.
