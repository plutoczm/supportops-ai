# Architecture

## Trust model

SupportOps AI treats model output, user-provided identifiers and tool arguments as untrusted. Identity and authorization are established before business data is accessed.

```text
                 Identity Provider
                       |
                 signed access token
                       |
        +--------------+--------------+
        |                             |
   FastAPI resource              MCP resource
      boundary                      boundary
        |                             |
        +-------- verified Principal -+
                       |
                  Guardrails
                       |
                  Intent Router
                 /      |       \
         Knowledge    reads    mutations
            |            |         |
       Hybrid RAG     customer      policy
            |         scoped        gate
        evidence                      |
                       +--------------+--------------+
                       |                             |
                customer confirm                 human ticket
                       |                             |
                  idempotent                    SLA/assignment
                    execute                      state machine
                       |                             |
                       +------------ audit ----------+
```

## Identity and authorization

### HTTP API

Production mode verifies a JWT against configured issuer, audience, JWKS and a fixed signature algorithm before creating a `Principal`. Customer identity is taken from the validated claim, not from support-message/action payloads. `support_agent`/`support_admin` roles gate the human-agent workspace.

Development mode requires explicit identity headers and is documented as local-only.

### MCP

Streamable HTTP JWT mode uses the MCP SDK resource-server hooks (`TokenVerifier`, `AuthSettings`, `get_access_token`). Customer-facing MCP tools do not accept `customer_id`; they derive customer scope from the verified access token.

`stdio` and in-memory clients do not have the HTTP bearer-token layer, so local tests use an explicit server-side demo customer configuration. This is a different trust boundary, not a production authentication substitute.

## Hybrid retrieval path

Retrieval is a bounded application subsystem rather than a direct `query -> LLM` shortcut.

```text
                         +--> BM25 sparse retrieval --------+
                         |                                   |
query -> tokenize -------+                                   |
                         |                                   v
                         +--> embedding provider -> dense -> weighted RRF
                                   |                         |
                       local deterministic                  v
                           or production              score-aware rerank
                             embedding                      |
                                   |                         v
                              local memory              evidence score
                              or Qdrant                     |
                                                           v
                                                   answerability gate
                                                    /             \
                                               citations         abstain
                                                   |
                                            grounded composer
```

### Local/CI retrieval

CI must not depend on paid APIs or a downloaded embedding model. The local dense leg therefore uses a deterministic hashed-vector representation. It is reproducible and useful as a regression signal but is **not a semantic embedding model**.

The sparse leg is BM25. Dense and sparse candidate lists are first fused with weighted reciprocal-rank fusion. A deterministic second-stage reranker then uses normalized BM25 score, dense score, query/title coverage and the fused rank signal. Ranking is intentionally separate from the evidence score used for answerability.

### Production retrieval

`EMBEDDING_BACKEND=openai` uses an OpenAI-compatible `/embeddings` endpoint. `KNOWLEDGE_BACKEND=qdrant` stores and queries the resulting **dense vectors** in Qdrant. The application still runs BM25 for the sparse leg and applies the same fusion/reranking/answerability contract.

The deployment image includes the optional Qdrant client dependency and the `rag` Compose profile is syntax-validated in CI. This verifies packaging/configuration only; CI does **not yet** claim end-to-end quality or availability of an external embedding provider + Qdrant deployment.

The current implementation does **not** claim Qdrant sparse-vector indexing, document ingestion pipelines, a learned cross-encoder reranker, or production semantic-quality metrics. Those remain separate measurable milestones.

### Answerability and citations

A retrieval result must clear an evidence threshold before the Knowledge service exposes citations. Unsupported queries are expected to return no citation and trigger an insufficient-evidence/human-support response. Deterministic answers retain `[KB-...]` source ids; optional model-generated answers are prompted to retain supplied source ids for factual policy claims.

## Mutation safety invariants

1. Model output never directly authorizes a refund or return.
2. Customer identity never comes from an LLM-selected tool argument.
3. Cross-customer order/ticket reads return not-found rather than leaking resource existence.
4. Refund/return side effects require a persisted pending action plus explicit customer confirmation.
5. High-value refunds bypass autonomous execution and create a high-priority human-review ticket.
6. The MCP surface intentionally exposes `request_refund`, not a confirmation/execution tool.
7. Action IDs are idempotency keys; retrying confirmation cannot duplicate the side effect.
8. A customer can cancel a pending action without a business mutation.
9. Prompt-injection detection runs before model and tool execution.
10. Tool and policy operations emit durable audit records keyed by trace and actor.
11. Insufficient retrieval evidence must fail closed into abstention rather than inventing a support policy.

## Human ticket workflow

Tickets persist priority, assignee, SLA deadline, timestamps and transition history. Application-level validation allows only explicit state transitions; direct arbitrary state updates are not exposed through the API.

```text
open -> assigned -> pending_customer -> assigned
          |                |
          +------------> resolved -> closed
                           |
                           +-------> open (reopen)
```

A ticket cannot be resolved before assignment. Closed tickets cannot be reassigned.

## Database release path

Local tests can opt into SQLAlchemy `create_all()` for isolated temporary databases. The deployment path does not: the application image sets `DATABASE_AUTO_CREATE_SCHEMA=false` and runs `alembic upgrade head` before API startup.

CI starts a clean PostgreSQL 17 service and executes `upgrade head`, `current --check-heads`, and `alembic check`. This gives the schema an explicit, replayable revision history and fails a pull request when ORM metadata changes without a matching migration.

## Current adapters

- API: FastAPI
- Authentication: development principal headers or JWT/JWKS resource-server verification
- Persistence: SQLAlchemy, SQLite locally, PostgreSQL in Docker Compose
- Schema evolution: Alembic migrations, validated against PostgreSQL in CI
- Model: optional OpenAI-compatible chat-completions endpoint
- Embeddings: deterministic local fallback or OpenAI-compatible embedding endpoint
- MCP: official Python SDK v2
- Sparse retrieval: application-side BM25
- Dense retrieval: in-memory adapter or Qdrant dense-vector adapter
- Fusion/reranking: weighted RRF plus deterministic score-aware reranker
- Evaluation: 140-case routing/safety benchmark, 60-case retrieval benchmark, and stateful integration tests

Distributed state, production ingestion/versioning, external retrieval integration testing and learned rerankers remain separate future milestones so their benefit can be measured rather than added as architecture decoration.
