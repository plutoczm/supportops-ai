# Retrieval: operating contract and limitations

This document makes the RAG boundary explicit so local regression machinery is not confused with production semantic retrieval.

## Components

| Stage | Local / CI | Production-capable adapter |
|---|---|---|
| Sparse candidate generation | BM25 in process | BM25 in process |
| Dense representation | deterministic hashed vector | OpenAI-compatible embedding endpoint |
| Dense storage/search | in-memory vectors | Qdrant named dense vector |
| Candidate fusion | weighted RRF | weighted RRF |
| Second-stage ranking | deterministic score-aware reranker | same reranker |
| Answerability | evidence threshold | same contract, threshold must be revalidated |
| Grounding | source-id citations / abstention | same contract |

The deterministic hashed vector is not a semantic embedding model. Its purpose is reproducible CI and local development without network/model dependencies.

## Local deterministic mode

```bash
pip install -e ".[dev]"
python -m evals.run_retrieval_evals
```

Configuration:

```text
KNOWLEDGE_BACKEND=local
EMBEDDING_BACKEND=deterministic
RETRIEVAL_MIN_EVIDENCE_SCORE=0.16
```

The fixed benchmark currently has 50 supported queries and 10 deliberately unsupported questions. Changes to tokenization, knowledge text, fusion, reranking or the evidence threshold must pass the same benchmark rather than weakening its gates.

## Qdrant dense mode

Install the optional adapter when running outside the prebuilt image:

```bash
pip install -e ".[rag]"
```

Start the optional vector-store service:

```bash
docker compose --profile rag up -d qdrant
```

Provide real embedding configuration before switching the application backend:

```text
KNOWLEDGE_BACKEND=qdrant
EMBEDDING_BACKEND=openai
EMBEDDING_BASE_URL=https://embedding-provider.example/v1
EMBEDDING_API_KEY=...
EMBEDDING_MODEL=...
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=supportops_knowledge
```

The application rejects `KNOWLEDGE_BACKEND=qdrant` with the deterministic embedding backend. This prevents a CI-only representation from silently becoming a production configuration.

## Why sparse retrieval is still application-side

The current milestone validates the architectural contract first: a sparse retriever, a dense retriever, fusion, reranking, answerability and citations. Qdrant currently stores the dense leg only. Moving sparse vectors into Qdrant should be a separate change with a before/after retrieval benchmark and an operational reason, not a resume keyword change.

## Known limitations

- Knowledge documents are currently versioned in source code rather than ingested through an external document pipeline.
- There is no chunk-level document version lineage or incremental re-index job yet.
- Qdrant/embedding provider outage, timeout and stale-index behavior are not yet covered by integration CI.
- The deterministic benchmark is small and curated; it does not measure production semantic quality on unseen support corpora.
- The reranker is deterministic and hand-calibrated, not a learned cross-encoder.
- Source-id citation presence is checked; multi-citation precision/recall and claim-level faithfulness are not yet measured.
- The production embedding model is intentionally vendor-neutral and therefore no embedding-model quality claim is made in the repository.

## Next acceptance criteria

A production-ingestion milestone should add:

1. immutable document/version identifiers and chunk provenance;
2. incremental index upsert/delete behavior;
3. embedding-provider and Qdrant timeout/degradation tests;
4. a larger held-out retrieval set separated from tuning cases;
5. latency measurements for sparse, dense, rerank and end-to-end retrieval;
6. citation precision/recall for multi-document answers;
7. an A/B report before replacing the deterministic reranker with a learned model.
