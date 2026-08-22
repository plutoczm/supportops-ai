# SupportOps AI

Production-oriented **AI Customer Operations Platform** for e-commerce/SaaS support.

Unlike simple chatbot demos, SupportOps AI focuses on production Agent engineering boundaries:

- bounded LLM authority
- grounded RAG retrieval
- safe business tool execution
- human-in-the-loop escalation
- durable workflow state
- auditability
- measurable evaluation

## Project Highlights

| Capability | Implementation |
| --- | --- |
| Agent Workflow | Intent routing + application orchestrator + business tools |
| RAG | BM25 + Dense Retrieval + Weighted RRF + Reranking + Answerability Gate |
| Business Actions | Refund / return / ticket workflows with policy checks |
| Security | Identity verification, customer isolation, injection defense, PII protection |
| Reliability | PostgreSQL durable state + Redis coordination + typed degradation |
| Observability | OpenTelemetry traces + Prometheus metrics |
| Evaluation | Stateful E2E regression framework |

## Architecture Overview

```text
Customer
   |
   v
FastAPI Gateway
   |
Input Guardrails
   |
Intent Router
   |
Application Orchestrator
   |
 +----------------------+-------------------+
 |                      |                   |
RAG Knowledge       Read Tools        Mutation Tools
 |                      |                   |
Qdrant/BM25        Order Query      Refund/Return
 |                                      |
Answerability                  Policy + Confirmation
 |                                      |
Response                         Audit + State
```

Detailed design:

- `docs/ARCHITECTURE.md`
- `docs/DEMO.md`
- `docs/E2E_EVALUATION.md`

## Safety Design

The LLM does not directly execute sensitive operations.

Example refund workflow:

```text
User Request
    |
Identity Verification
    |
Order Validation
    |
Refund Policy Check
    |
Risk Assessment
    |
Pending Action
    |
Authenticated Confirmation
    |
Idempotent Execution
    |
Audit Record
```

This prevents hallucinated or unauthorized business mutations.

## Hybrid RAG Pipeline

```text
Query
 |
 +--> BM25 Retrieval
 |
 +--> Dense Retrieval
          |
          v
        RRF Fusion
          |
        Reranker
          |
   Answerability Gate
          |
 Grounded Response + Citation
```

## Evaluation

The project includes stateful end-to-end evaluation rather than only answer similarity scoring.

Metrics include:

- workflow/tool selection
- task completion
- tool arguments
- citation consistency
- hallucinated action rate
- confirmation safety
- cross-customer isolation

Latest verified baseline:

```text
Application coverage: 81.54%
Routing safety cases: 140
Retrieval cases: 60
E2E regression: v1 61 scenarios / v2 60 scenarios
Unsafe mutation rate: 0
```

Detailed evaluation methodology is documented in `docs/E2E_EVALUATION.md`.

## Tech Stack

Backend:

- FastAPI
- PostgreSQL
- Redis
- SQLAlchemy
- Alembic

AI:

- RAG
- MCP
- Tool Calling
- OpenAI-compatible LLM/Embedding APIs
- Qdrant

Engineering:

- Docker Compose
- GitHub Actions
- pytest
- Ruff
- OpenTelemetry
- Prometheus

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

make up
```

Development commands:

```bash
make test
make lint
make eval
```

## Repository Structure

```text
app/
 ├── api              # HTTP interfaces
 ├── agents           # Agent workflow
 ├── tools            # Business capabilities
 ├── rag              # Retrieval pipeline
 ├── guardrails       # Safety controls
 └── core             # Configuration and infrastructure

 evals/               # Evaluation framework
tests/               # Unit and integration tests
docs/                # Architecture and engineering docs
```

## Engineering Status

The main feature surface is intentionally near feature freeze.

Future improvements focus on production evidence:

- external evaluation datasets
- production SLO calibration
- outbox workflow for long-running external mutations

Adding more Agent roles is not a priority; reliability and evaluation quality are the focus.

## License

MIT
