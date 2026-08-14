# Evaluation contract

SupportOps AI separates deterministic business/safety assertions, retrieval-quality regression, stateful application tests and external-adapter integration. A pull request must remain reproducible without a paid LLM before optional model-quality evaluation is considered.

## Routing and safety benchmark v2

`evals/cases.py` contains **140 curated deterministic cases** across knowledge/policy questions, order status, refund, return, complaint/human handoff, unsupported requests, prompt injection and PII-bearing requests.

The runner reports overall routing accuracy, macro-F1, per-intent precision/recall/F1, prompt-injection block recall, PII redaction recall, mutating-action policy accuracy and unsafe mutation count.

Current gates:

- cases >= 120
- routing accuracy >= 0.97
- routing macro-F1 >= 0.96
- prompt-injection block recall = 1.0
- PII redaction recall = 1.0
- mutating-action policy accuracy = 1.0
- unsafe mutation count = 0

Latest verified v0.4 result:

- cases: **140**
- routing accuracy: **1.0**
- routing macro-F1: **1.0**
- all six per-intent precision/recall/F1 values: **1.0**
- prompt-injection block recall: **1.0**
- PII redaction recall: **1.0**
- mutating-action policy accuracy: **1.0**
- unsafe mutation count: **0**

## Retrieval benchmark v1

`evals/retrieval_cases.py` contains **60 bilingual deterministic cases**: 50 supported queries across ten support topics and 10 deliberately unsupported queries.

`python -m evals.run_retrieval_evals` measures:

- Recall@1
- Recall@3
- MRR@3
- deterministic grounded-answer source-id presence
- unsupported-query abstention recall

Current gates:

- cases >= 60
- Recall@1 >= 0.94
- Recall@3 = 1.0
- MRR@3 >= 0.97
- answer citation presence = 1.0
- unsupported-query abstention recall >= 0.90

Latest verified v0.4 result:

- cases: **60**
- supported / unsupported: **50 / 10**
- Recall@1: **1.0**
- Recall@3: **1.0**
- MRR@3: **1.0**
- grounded-answer citation presence: **1.0**
- unsupported-query abstention recall: **1.0**
- failures: **0**

The first hybrid implementation exposed a real ranking problem: Recall@1 was 0.92 while Recall@3 was already 1.0 and MRR@3 was 0.96. Rank-only weighted RRF did not remove the same errors, so score-aware reranking was added without weakening the acceptance gates.

This fixed benchmark uses the deterministic local retrieval path. It is a regression contract, **not proof of real-world semantic retrieval quality** for an external embedding model.

## Stateful application tests

Regular pytest validates properties that aggregate benchmarks cannot express, including:

- authenticated principal requirements and JWT verification
- customer/agent role separation and cross-customer isolation
- explicit refund/return confirmation, cancellation and idempotency
- high-value human review and ticket/SLA state transitions
- trace-linked audit records
- MCP server-side customer scope
- deterministic embedding stability
- unsupported-query abstention
- versioned knowledge source/chunk lineage
- stable chunk identity with content-hash change detection
- typed embedding timeout handling
- runtime dense-search failure -> visible sparse fallback
- fallback-disabled dense-search failure -> propagated error
- Qdrant mode rejects the deterministic test-only embedding
- Qdrant startup/index failure -> sparse-only startup when explicitly allowed
- the same startup/index failure -> fail fast when fallback is disabled

Latest regular test result:

- **37 passed, 1 skipped**
- application coverage: **80.08%**
- coverage gate: **75%**

The skipped module is the real-Qdrant integration suite during the first lightweight `.[dev]` test phase. CI installs the `rag` extra later and executes that integration suite explicitly.

## Real Qdrant lifecycle integration

CI starts **Qdrant v1.18.2** as a service container and then installs the optional Python `rag` adapter. The integration suite uses a local HTTP server implementing the OpenAI-compatible `/embeddings` protocol, backed by a deterministic 64-dimensional test representation.

This verifies an external protocol and a real vector-store process while remaining deterministic and network-independent. It does **not** establish semantic quality for a production embedding model.

The integration currently checks:

1. first sync of two desired chunks -> two embeddings and two upserts;
2. identical second sync -> zero embeddings/upserts and two unchanged chunks;
3. one changed document + one removed document -> one changed-only embedding/upsert and one stale-vector deletion;
4. dense query returns the expected indexed document with source lineage;
5. post-sync Qdrant query outage maps to typed `qdrant_unavailable`.

Latest result: **2 integration tests passed**.

The Qdrant service logs in CI show real collection-existence checks, collection creation, point upserts, scrolls, stale-point deletion and query requests. This is materially stronger than mocking the Qdrant client in unit tests.

## Database and deployment contracts

CI also validates:

```bash
alembic upgrade head
alembic current --check-heads
alembic check

docker compose config -q
docker compose --profile rag config -q

docker build -t supportops-ai:ci .
```

The latest image build packages `supportops-ai==0.4.0` with the optional `rag` dependency and the bundled versioned knowledge JSON.

## Interpretation limits

The verified numbers are **curated deterministic regression/integration metrics**. They must not be presented as:

- production customer-support accuracy;
- security efficacy against arbitrary attacks;
- semantic quality of an external embedding model;
- Qdrant high availability or multi-node failover;
- claim-level faithfulness for arbitrary multi-document generation;
- real-world latency/cost SLOs.

## Next evaluation layer

The next high-value evaluation work is larger held-out retrieval/conversation data, tool-selection and argument accuracy, task completion/escalation, claim-level citation precision/faithfulness, hallucinated-action rate, and P95 latency/token/cost reporting once observability is instrumented. Optional LLM-as-judge metrics may complement deterministic business assertions but must not replace them.
