# Evaluation contract

SupportOps AI separates deterministic business/safety assertions, retrieval-quality regression, stateful application tests, observability regression and external-adapter integration. A pull request must remain reproducible without a paid LLM before optional model-quality evaluation is considered.

## Routing and safety benchmark v2

`evals/cases.py` contains **140 curated deterministic cases** across knowledge/policy questions, order status, refund, return, complaint/human handoff, unsupported requests, prompt injection and PII-bearing requests.

Acceptance gates include routing accuracy >= 0.97, macro-F1 >= 0.96, injection-block recall = 1.0, PII-redaction recall = 1.0, mutation-policy accuracy = 1.0 and unsafe mutation count = 0.

Latest verified v0.6 result: **140 cases**, routing accuracy **1.0**, macro-F1 **1.0**, all six per-intent precision/recall/F1 values **1.0**, injection block **1.0**, PII redaction **1.0**, mutation-policy accuracy **1.0**, unsafe mutations **0**.

## Retrieval benchmark v1

The fixed bilingual retrieval set contains **60 deterministic cases**: 50 supported queries and 10 deliberately unsupported queries. Gates remain Recall@1 >= 0.94, Recall@3 = 1.0, MRR@3 >= 0.97, citation presence = 1.0 and unsupported abstention >= 0.90.

Latest verified v0.6 result: Recall@1 **1.0**, Recall@3 **1.0**, MRR@3 **1.0**, citation presence **1.0**, unsupported abstention **1.0**, failures **0**.

These metrics use the deterministic local retrieval path and are regression signals, not proof of external embedding semantic quality.

## Stateful application tests

Regular pytest validates existing auth/tool/ticket/RAG/reliability invariants plus the observability contract. Current observability tests verify that route/operation metrics are emitted, high-cardinality customer/conversation identifiers do not enter Prometheus labels, metrics can be disabled, typed dependency failures increment degradation metrics, and an incoming W3C `traceparent` is accepted without leaking into metric labels.

Latest regular run: **46 passed, 2 skipped**, application coverage **81.45%** under a 75% gate. `app/observability.py` itself is at **92%** statement coverage in that run.

The two skips are external integration modules during the lightweight first pytest phase; CI runs Redis explicitly and later installs the Qdrant `rag` extra and runs Qdrant explicitly.

## Local observability latency regression v1

`python -m evals.run_slo_smoke` is a deterministic pull-request regression workload, not a production load test. It executes 30 knowledge/policy and 30 order-status requests through FastAPI TestClient using SQLite and deterministic local retrieval.

Current acceptance contract:

- exactly 60 requests;
- success rate = 1.0 and errors = 0;
- no unexpected retrieval degradation;
- expected HTTP/operation/degradation metrics must exist;
- local HTTP P95 must remain under a deliberately loose 750 ms catastrophic-regression budget.

Latest verified v0.6 result:

```text
requests: 60
success_rate: 1.0
error_count: 0
degraded_responses: 0
http_p50_ms: 5.652
http_p95_ms: 8.508
knowledge_p95_ms: 8.924
order_p95_ms: 6.745
```

The metric-contract checks all passed for the HTTP histogram, operation histogram, degradation counter and router/retrieval/tool operations.

These latency numbers must **not** be used as a production SLO. They do not include networked PostgreSQL/Redis/Qdrant, an external chat model, an external embedding provider, real concurrency, multi-replica traffic, collector/exporter overhead under sustained load, or production network/storage behavior.

## Real Redis reliability integration

CI starts a real standalone `redis:7.4-alpine` service. Two independent `RedisReliabilityCoordinator` objects point to that same process and verify shared action-lock exclusion/release, confirmation TTL presence and shared atomic fixed-window rate state.

Latest result: **1 integration test passed**.

This proves the protocol/control path against a real standalone Redis process. It does **not** test Sentinel/Cluster failover, network partitions, replica promotion or exactly-once execution.

## Real Qdrant lifecycle integration

CI also starts Qdrant v1.18.2 and a local HTTP server implementing the OpenAI-compatible embeddings protocol with a deterministic test vector. It verifies first sync, zero-work unchanged resync, changed-only upsert, stale deletion, dense query and typed Qdrant outage.

Latest result: **2 integration tests passed**.

The deterministic embedding is a protocol/index-lifecycle fixture, not a semantic-quality claim.

## Database and deployment contracts

The v0.6 CI runs:

```bash
alembic upgrade head
alembic current --check-heads
alembic check

docker compose config -q
docker compose --profile rag config -q

docker build -t supportops-ai:ci .
```

The successful code-head run upgraded PostgreSQL through revision `20260814_0002`, reported no missing migration operations and built an image containing `supportops-ai==0.6.0` with Prometheus/OpenTelemetry, Redis and the optional Qdrant adapter.

## Interpretation limits

The verified numbers are curated deterministic regression/integration metrics. They must not be presented as production customer-support accuracy, arbitrary-attack security efficacy, exactly-once mutation delivery, Redis or Qdrant HA, external embedding semantic quality, claim-level faithfulness for arbitrary generated answers, or real-world production latency/cost SLOs.

## Next evaluation layer

The next highest-value layer is a held-out multi-turn end-to-end conversation/tool benchmark: tool-selection accuracy, argument accuracy, task completion, escalation recall, hallucinated-action rate, mutation confirmation/cancellation safety and claim-level citation precision/faithfulness. Observability should report latency/error/degradation alongside those task metrics. Production SLO thresholds should be calibrated from real deployment telemetry rather than copied from the deterministic CI workload.
