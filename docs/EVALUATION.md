# Evaluation contract

SupportOps AI separates deterministic business/safety assertions, retrieval-quality regression, stateful application tests and external-adapter integration. A pull request must remain reproducible without a paid LLM before optional model-quality evaluation is considered.

## Routing and safety benchmark v2

`evals/cases.py` contains **140 curated deterministic cases** across knowledge/policy questions, order status, refund, return, complaint/human handoff, unsupported requests, prompt injection and PII-bearing requests.

Acceptance gates include routing accuracy >= 0.97, macro-F1 >= 0.96, injection-block recall = 1.0, PII-redaction recall = 1.0, mutation-policy accuracy = 1.0 and unsafe mutation count = 0.

Latest verified v0.5 result: **140 cases**, routing accuracy **1.0**, macro-F1 **1.0**, all six per-intent precision/recall/F1 values **1.0**, injection block **1.0**, PII redaction **1.0**, mutation-policy accuracy **1.0**, unsafe mutations **0**.

## Retrieval benchmark v1

The fixed bilingual retrieval set contains **60 deterministic cases**: 50 supported queries and 10 deliberately unsupported queries. Gates remain Recall@1 >= 0.94, Recall@3 = 1.0, MRR@3 >= 0.97, citation presence = 1.0 and unsupported abstention >= 0.90.

Latest verified v0.5 result: Recall@1 **1.0**, Recall@3 **1.0**, MRR@3 **1.0**, citation presence **1.0**, unsupported abstention **1.0**, failures **0**.

These metrics use the deterministic local retrieval path and are regression signals, not proof of external embedding semantic quality.

## Stateful application tests

Regular pytest now validates, among other existing auth/tool/ticket/RAG properties:

- durable pending action `created_at/expires_at`;
- expired confirmation cannot produce a business side effect;
- action-scoped lock rejects overlapping resolution attempts;
- mutation coordination failure defaults to fail closed;
- support-message rate limit returns 429 with `Retry-After`;
- prior explicit confirmation/cancellation/idempotency and cross-customer isolation invariants remain intact;
- typed retrieval fallback/fail-fast behavior remains intact.

Latest regular run: **42 passed, 2 skipped**, application coverage **79.17%** under a 75% gate.

The two skips are external integration modules during the lightweight first pytest phase; CI runs Redis explicitly and later installs the Qdrant `rag` extra and runs Qdrant explicitly.

## Real Redis reliability integration

CI starts a real standalone `redis:7.4-alpine` service. Two independent `RedisReliabilityCoordinator` objects point to that same process and verify:

1. first coordinator acquires an action lease and the second cannot acquire the same lease;
2. token-checked release allows a subsequent acquisition;
3. confirmation TTL is actually stored in Redis with a bounded TTL;
4. fixed-window rate-limit state is shared across coordinators and atomically denies the request after the configured limit.

Latest result: **1 integration test passed**.

This proves the protocol/control-path behavior against a real standalone Redis process. It does **not** test Sentinel/Cluster failover, network partitions, replica promotion or exactly-once execution.

## Real Qdrant lifecycle integration

CI also starts Qdrant v1.18.2 and a local HTTP server that implements the OpenAI-compatible embeddings protocol using a deterministic test vector. It verifies first sync, zero-work unchanged resync, changed-only upsert, stale deletion, dense query and typed Qdrant outage.

Latest result: **2 integration tests passed**.

The deterministic embedding is a protocol/index-lifecycle fixture, not a semantic-quality claim.

## Database and deployment contracts

The v0.5 CI runs:

```bash
alembic upgrade head
alembic current --check-heads
alembic check

docker compose config -q
docker compose --profile rag config -q

docker build -t supportops-ai:ci .
```

The successful run upgraded PostgreSQL through revision `20260814_0002`, reported no missing migration operations and built an image containing `supportops-ai==0.5.0` with Redis plus the optional Qdrant adapter.

## Interpretation limits

The verified numbers are curated deterministic regression/integration metrics. They must not be presented as production customer-support accuracy, arbitrary-attack security efficacy, exactly-once mutation delivery, Redis or Qdrant HA, external embedding semantic quality, claim-level faithfulness for arbitrary generated answers, or real-world latency/cost SLOs.

## Next evaluation layer

The next high-value layer is observability-backed performance/reliability evaluation: instrument route/retrieval/Redis/Qdrant/tool/policy spans and counters, then run reproducible load scenarios that report P50/P95 latency, error/degradation rates, rate-limit behavior and tool latency. After that, expand to held-out end-to-end conversations measuring tool-selection/argument accuracy, task completion, escalation recall and hallucinated-action rate.
