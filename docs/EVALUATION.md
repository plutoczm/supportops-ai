# Evaluation contract

SupportOps AI separates deterministic business/safety assertions from model-quality experiments. A pull request must be reproducible without a paid LLM before optional model evaluation is considered.

## Routing and safety benchmark v2

`evals/cases.py` builds the versioned deterministic regression set. It currently contains **140 cases** across:

- knowledge/policy questions
- order status
- refund
- return
- complaint/human handoff
- unsupported/unknown requests
- prompt injection
- PII-bearing requests

The runner reports:

- overall routing accuracy
- macro-F1 across all routing intents
- per-intent precision/recall/F1
- prompt-injection block recall
- PII redaction recall
- mutating-action policy accuracy
- unsafe mutation count

Current gates are intentionally strict:

- cases >= 120
- routing accuracy >= 0.97
- routing macro-F1 >= 0.96
- prompt-injection block recall = 1.0 for the curated attack set
- PII redaction recall = 1.0 for the curated PII set
- mutating-action policy accuracy = 1.0
- unsafe mutation count = 0

### Current CI baseline

The latest verified foundation run reports:

- cases: **140**
- routing accuracy: **1.0**
- routing macro-F1: **1.0**
- all six per-intent precision/recall/F1 values: **1.0**
- prompt-injection block recall: **1.0**
- PII redaction recall: **1.0**
- mutating-action policy accuracy: **1.0**
- unsafe mutation count: **0**

The expanded benchmark was useful before reaching that result: it exposed `how does shipping policy work?` as a false `order_status` classification. The fix distinguishes policy/rules questions without an order identifier from shipping/order tracking, and a dedicated unit regression test preserves that behavior.

These numbers are **regression-test metrics**, not estimates of real-world customer-support accuracy, security efficacy, or LLM quality. A hand-curated deterministic benchmark can be fully correct and still fail on unseen language or attacks.

## Stateful integration properties

Pytest separately verifies properties a text-routing benchmark cannot:

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

The latest verified run has **26 passing tests** and **82.55% application coverage** under a 75% coverage gate.

## Database migration contract

CI starts PostgreSQL 17 and executes:

```bash
alembic upgrade head
alembic current --check-heads
alembic check
```

This validates both revision application and the absence of ORM schema changes that would require an uncommitted migration.

## Next evaluation layer

The next benchmark should exercise complete conversations and adapters, measuring tool-selection precision/recall, argument accuracy, task completion, escalation recall, citation precision/recall, groundedness, hallucinated-action rate, P95 latency and token/cost budgets. LLM-as-judge metrics may complement deterministic business assertions but must not replace them.
