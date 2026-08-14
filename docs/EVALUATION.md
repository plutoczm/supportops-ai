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

These numbers are **regression-test metrics**, not estimates of real-world customer-support accuracy or security efficacy.

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

## Next evaluation layer

The next benchmark should exercise complete conversations and adapters, measuring tool-selection precision/recall, argument accuracy, task completion, escalation recall, citation precision/recall, groundedness, hallucinated-action rate, P95 latency and token/cost budgets. LLM-as-judge metrics may complement deterministic business assertions but must not replace them.
