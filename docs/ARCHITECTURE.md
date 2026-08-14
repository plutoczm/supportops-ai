# Architecture

## Production boundary

SupportOps AI treats the LLM as an untrusted reasoning component, not as the authorization layer.

```text
Customer/API
   |
Input Guardrails -----> block prompt-injection / redact PII
   |
Intent Router --------> LLM classification with deterministic fallback
   |
Application Orchestrator
   |          |             |
Knowledge   Read tools    Mutating intent
   |          |             |
Evidence   ownership      Action Policy
                         /           \
                 confirmation      human review
                      |                 |
               pending action        ticket
                      |
             authenticated confirm API
                      |
                idempotent tool
```

## Safety invariants

1. Model output never directly authorizes a refund or return.
2. Cross-customer order/ticket reads return not-found rather than leaking existence.
3. Refund/return side effects require a persisted pending action plus explicit confirmation.
4. High-value refunds bypass autonomous execution and create a human-review ticket.
5. The MCP surface intentionally exposes `request_refund`, not `confirm_refund`.
6. Action IDs are idempotency keys, so retrying confirmation does not duplicate a side effect.
7. Prompt-injection detection runs before model and tool execution.

## Current adapters

- API: FastAPI
- Persistence: SQLAlchemy, SQLite locally, PostgreSQL in Docker Compose
- Model: optional OpenAI-compatible chat-completions endpoint
- MCP: official Python SDK v2
- Retrieval: deterministic local evidence baseline

The retrieval adapter is deliberately simple in the foundation PR. A later milestone replaces it with hybrid dense/sparse retrieval and a reranker while preserving the same `KnowledgeService` boundary.
