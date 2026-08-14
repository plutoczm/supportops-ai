# Evaluation contract

SupportOps AI separates deterministic business/safety assertions from retrieval-quality and optional model-quality experiments. A pull request must be reproducible without a paid LLM before optional model evaluation is considered.

## Routing and safety benchmark v2

`evals/cases.py` builds the versioned deterministic regression set. It contains **140 cases** across knowledge/policy questions, order status, refund, return, complaint/human handoff, unsupported requests, prompt injection and PII-bearing requests.

The runner reports overall routing accuracy, macro-F1, per-intent precision/recall/F1, prompt-injection block recall, PII redaction recall, mutating-action policy accuracy and unsafe mutation count.

Current gates:

- cases >= 120
- routing accuracy >= 0.97
- routing macro-F1 >= 0.96
- prompt-injection block recall = 1.0 for the curated attack set
- PII redaction recall = 1.0 for the curated PII set
- mutating-action policy accuracy = 1.0
- unsafe mutation count = 0

Current verified code baseline:

- cases: **140**
- routing accuracy: **1.0**
- routing macro-F1: **1.0**
- all six per-intent precision/recall/F1 values: **1.0**
- prompt-injection block recall: **1.0**
- PII redaction recall: **1.0**
- mutating-action policy accuracy: **1.0**
- unsafe mutation count: **0**

The expanded benchmark previously exposed `how does shipping policy work?` as a false `order_status` classification. The implementation was fixed and a dedicated unit regression test preserves the policy-vs-tracking boundary.

## Retrieval benchmark v1

`evals/retrieval_cases.py` contains **60 deterministic bilingual cases**:

- **50 supported queries** across ten support knowledge documents
- **10 unsupported queries** that should not be answered from the support knowledge base

`python -m evals.run_retrieval_evals` measures:

- **Recall@1**: whether a relevant knowledge document is the first result
- **Recall@3**: whether it appears in the first three results
- **MRR@3**: reciprocal-rank quality of the first relevant result
- **grounded-answer citation presence**: deterministic answer retains the retrieved source id
- **unsupported-query abstention recall**: unsupported questions return no citation rather than fabricating relevance

Current gates:

- cases >= 60
- Recall@1 >= 0.94
- Recall@3 = 1.0
- MRR@3 >= 0.97
- answer citation presence = 1.0
- unsupported-query abstention recall >= 0.90

Current verified code baseline:

- cases: **60**
- supported / unsupported: **50 / 10**
- Recall@1: **1.0**
- Recall@3: **1.0**
- MRR@3: **1.0**
- grounded-answer citation presence: **1.0**
- unsupported-query abstention recall: **1.0**
- failures: **0**

The first hybrid implementation did **not** pass these numbers: Recall@1 was **0.92**, Recall@3 was **1.0**, and MRR@3 was **0.96**. That pattern showed that candidate recall was sufficient but top-rank calibration was weak. Rank-only weighted RRF did not resolve the same errors, so the implementation added a score-aware reranker using normalized BM25 score, dense score, title coverage and the fused rank signal. The benchmark then passed without changing the acceptance gates.

This benchmark uses the deterministic local retrieval path. It validates ranking/abstention contracts and regression behavior; it is **not proof of real-world semantic-retrieval quality for an external embedding model or Qdrant deployment**. The current CI validates Qdrant-related packaging and Compose configuration, but does not yet run an end-to-end external embedding + Qdrant retrieval benchmark. Production embedding/vector-store changes should be evaluated against the same labeled queries plus a larger held-out corpus.

## Stateful integration properties

Pytest verifies properties the text benchmarks cannot:

- explicit authenticated principal is required
- JWT signature/issuer/audience/subject verification
- customer/agent role separation
- cross-customer data isolation
- persisted pending actions
- customer cancellation with no side effect
- explicit confirmation before refund/return
- idempotent confirmation retries
- high-value refund human review
- ticket priority, SLA and validated state transitions
- trace-linked audit events
- MCP tools derive customer scope server-side instead of accepting `customer_id`
- Alembic migrations can initialize a clean PostgreSQL database and match ORM metadata
- deterministic embeddings are stable and normalized
- unsupported retrieval can abstain
- Qdrant mode rejects the CI-only deterministic embedding backend

The verified v0.3 code run has **31 passing tests** and **81.16% application coverage** under a 75% coverage gate.

## Database and deployment contracts

CI starts PostgreSQL 17 and executes:

```bash
alembic upgrade head
alembic current --check-heads
alembic check
```

It also validates both default and `rag` Docker Compose configurations, then builds the application image with the optional `rag` dependency set.

## Next evaluation layer

The next benchmark should exercise complete conversations and external adapters, measuring tool-selection precision/recall, argument accuracy, task completion, escalation recall, citation precision/recall on multi-chunk answers, groundedness, hallucinated-action rate, embedding/Qdrant degradation behavior, P95 latency and token/cost budgets. LLM-as-judge metrics may complement deterministic business assertions but must not replace them.
