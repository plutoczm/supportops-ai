# Architecture

## Trust model

SupportOps AI treats model output, user-provided identifiers and external retrieval/tool adapters as untrusted. Identity, authorization, business policy and mutation confirmation are application concerns rather than model decisions.

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

Production HTTP mode verifies JWT signature, issuer, audience, required temporal claims and subject before creating a `Principal`. Customer identity is derived from validated claims, not message/action payloads. `support_agent` and `support_admin` roles gate the human workspace.

MCP Streamable HTTP uses the SDK resource-server hooks. Customer-facing MCP tools do not accept `customer_id`; customer scope comes from the verified access token. The MCP surface intentionally prepares refund requests but does not expose the final confirmation/execution step.

## Knowledge lifecycle

The active knowledge set is stored as versioned source records rather than a Python constant:

```text
Knowledge source
  document_id
  version
  title
  text
  source_uri
        |
        v
Deterministic chunker
        |
        +--> stable chunk_id: document_id:version:ordinal
        +--> SHA-256 content_hash
        +--> source/version lineage
        |
        v
RetrievalDocument
```

The current source is a bundled JSON artifact. This gives deterministic version/chunk provenance and reproducible packaging, but it is not yet a multi-user document-management or publication system.

Citations expose `document_id`, `document_version`, `chunk_id` and `source_uri`. Knowledge-search audit events record chunk IDs and document versions so a support answer can be traced to the evidence version used at request time.

## Hybrid retrieval path

```text
                         +--> BM25 sparse retrieval --------+
                         |                                   |
query -> tokenize -------+                                   |
                         |                                   v
                         +--> embedding provider -> dense -> weighted RRF
                                   |                         |
                       deterministic local                  v
                         or production                score-aware rerank
                           embedding                        |
                                   |                         v
                            in-memory/Qdrant             evidence score
                                                             |
                                                             v
                                                     answerability gate
                                                      /             \
                                                 citations         abstain
                                                     |
                                              grounded composer
```

### Local deterministic mode

CI cannot depend on a paid API or downloaded embedding model. The local dense leg therefore uses a deterministic hashed representation. It is useful for reproducible regression testing but is **not a semantic embedding model**.

### Production-capable dense mode

`EMBEDDING_BACKEND=openai` calls an OpenAI-compatible `/embeddings` endpoint. `KNOWLEDGE_BACKEND=qdrant` stores and queries named dense vectors in Qdrant. BM25 remains application-side sparse retrieval, followed by the same weighted-RRF, deterministic reranker and answerability gate.

The application rejects Qdrant with the deterministic hash embedding. The current implementation also does not claim Qdrant sparse vectors or a learned cross-encoder reranker.

## Incremental Qdrant synchronization

Qdrant payload metadata includes stable index/chunk identity, source lineage and `content_hash`. Startup synchronization compares the desired source state with remote payload metadata:

```text
collection missing -> embed all -> create -> upsert all
collection exists  -> scroll remote metadata
                   -> unchanged hash: no embedding/upsert
                   -> changed hash: embed + upsert changed chunk only
                   -> remote id absent from desired state: delete stale vector
```

`IndexSyncStats` reports desired, embedded, upserted, deleted and unchanged chunk counts. This removes the previous behavior where every process start re-embedded and rewrote the complete knowledge set.

The current sync is a bounded single-process startup synchronization mechanism. It is **not** a distributed indexing coordinator, queue-driven ingestion service or transactional multi-replica publication protocol.

## Retrieval failure/degradation boundary

Embedding and vector-store failures are converted to typed retrieval reasons rather than arbitrary provider exceptions. Current reasons include embedding timeout/rate-limit/provider/invalid-response and Qdrant index/search failures.

With `RETRIEVAL_ALLOW_SPARSE_FALLBACK=true`:

```text
dense startup/search failure
          |
          v
 typed RetrievalBackendError
          |
          +--> dense unavailable
          +--> BM25 remains available
          +--> retrieval_degraded=true
          +--> explicit degradation_reason
          +--> audit outcome=degraded
```

With fallback disabled, the same error propagates and startup/search fails fast. The fallback is an availability policy, not a claim that sparse-only retrieval is equivalent to the configured dense system.

## Answerability and citations

Retrieval ranking and answerability are separate decisions. A result must clear the evidence threshold before citations are exposed. Unsupported questions are expected to return no evidence and trigger an insufficient-evidence/human-support response. This invariant also applies during sparse-only degradation; the system does not lower the answerability threshold just because the dense backend failed.

## Mutation safety invariants

1. Model output never authorizes a refund or return.
2. Customer identity never comes from an LLM-selected business-tool argument.
3. Cross-customer order/ticket reads fail without leaking resource existence.
4. Refund/return side effects require a persisted pending action and authenticated confirmation.
5. High-value refunds enter human review.
6. MCP does not expose the final mutation-confirmation step.
7. Action IDs are idempotency keys.
8. A customer can cancel a pending action without a mutation.
9. Prompt-injection detection runs before model/tool execution.
10. Business-tool, policy and ticket operations emit trace-linked audit records.
11. Insufficient retrieval evidence fails closed into abstention.
12. Dense retrieval failure is visible and policy-controlled; it cannot silently masquerade as a successful dense request.

## Human ticket workflow

```text
open -> assigned -> pending_customer -> assigned
          |                |
          +------------> resolved -> closed
                           |
                           +-------> open (reopen)
```

A ticket cannot be resolved before assignment, and closed tickets cannot be reassigned.

## Database release path

Production schema evolution is owned by Alembic. CI starts PostgreSQL 17 and runs `upgrade head`, `current --check-heads` and `alembic check`, failing when ORM metadata requires an uncommitted migration.

## CI adapter contract

The CI job now starts PostgreSQL 17 and a real Qdrant v1.18.2 service. After deterministic unit/eval gates, it installs the optional `rag` dependency and runs Qdrant lifecycle integration through a local HTTP server implementing the OpenAI-compatible embedding protocol.

That integration verifies protocol compatibility and index lifecycle behavior against a real vector-store process. The mock embedding representation is deterministic, so the test does **not** establish external embedding semantic quality or Qdrant high availability.

## Current adapters

- API: FastAPI
- Authentication: development headers or JWT/JWKS resource server
- Persistence: SQLAlchemy; SQLite local tests; PostgreSQL deployment/CI
- Schema evolution: Alembic
- Model: optional OpenAI-compatible chat completions
- Embeddings: deterministic local representation or OpenAI-compatible endpoint
- MCP: official Python SDK v2
- Sparse retrieval: application-side BM25
- Dense retrieval: in-memory or Qdrant named dense vectors
- Fusion/reranking: weighted RRF + deterministic score-aware reranker
- Knowledge source: versioned bundled JSON + deterministic chunker
- Index lifecycle: content-addressed changed-only Qdrant sync + stale deletion
- Evaluation: 140-case routing/safety, 60-case retrieval, stateful unit tests and real Qdrant lifecycle integration

Redis-backed distributed state, OTel/SLO export, external knowledge publication workflows, larger held-out semantic datasets and learned rerankers remain separate measurable milestones.
