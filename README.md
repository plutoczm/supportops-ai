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
| Local Workspace | FastAPI-hosted customer chat + agent ticket desk at `/ui/` |
| Human Handoff | Durable ticket messages, assigned-agent replies and customer-isolated recovery |

## Architecture Overview

```text
Customer
   |
   v
Local Workspace / FastAPI Gateway
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

When the automated workflow hands work to a person, the customer and assigned agent share a
durable ticket message thread. Customer messages move the ticket back to the agent queue;
agent replies move it to `pending_customer`. Sensitive mutations remain governed by the
existing confirmation flow.

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
Application coverage: 82.47%
Unit/API/UI regression: 64 passed, 2 integration tests skipped by default
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

## Local Operations Workspace

The local workspace is served by the same FastAPI application:

- Customer chat and grounded citations
- Explicit refund/return confirmation controls
- Human-handoff ticket creation
- Agent assignment, ticket state updates and internal notes
- Durable two-way customer/agent ticket messages

Open [http://localhost:8002/](http://localhost:8002/) after Docker startup. The technical API
surface remains available at [http://localhost:8002/docs](http://localhost:8002/docs).

### Human handoff lifecycle

```text
AI cannot safely complete request
          |
          v
ticket created with initial customer + AI context
          |
assigned agent opens the ticket conversation
          |
agent reply -> pending_customer
          |
customer reply -> assigned
```

Only the ticket customer can read or send customer messages. An agent must be assigned to the
ticket before replying; closed or resolved tickets reject new messages.

## Quick Start (Windows + Docker)

Prerequisites: Docker Desktop, Conda/Python 3.11+, and Ollama with
`qwen3-embedding:0.6b` available for the local Qdrant setup.

```powershell
conda activate supportops-ai
python -m pip install -e ".[dev,rag]"

# Copy .env.example to .env, then configure your OpenAI-compatible LLM values.
# Keep .env out of source control.

ollama list
docker compose --profile rag up --build -d
```

For the local Ollama + Qdrant retrieval mode used by the Docker profile, set these non-secret
values in `.env` (the Compose service maps the Docker-internal URLs automatically):

```dotenv
KNOWLEDGE_BACKEND=qdrant
EMBEDDING_BACKEND=openai
EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1
EMBEDDING_MODEL=qwen3-embedding:0.6b
EMBEDDING_DIMENSION=1024
EMBEDDING_TIMEOUT_SECONDS=60
QDRANT_URL=http://127.0.0.1:6333
QDRANT_COLLECTION=supportops_knowledge
```

Leave `EMBEDDING_API_KEY` and `QDRANT_API_KEY` empty for the local Ollama/Qdrant setup. Set
`LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` for your OpenAI-compatible chat provider.

Verify the local stack:

```powershell
curl --noproxy "*" http://127.0.0.1:8002/health
curl --noproxy "*" http://127.0.0.1:6333/readyz
```

Useful local addresses:

- Workspace: [http://localhost:8002/](http://localhost:8002/)
- Swagger: [http://localhost:8002/docs](http://localhost:8002/docs)
- Metrics: [http://localhost:8002/metrics](http://localhost:8002/metrics)
- Qdrant ready check: [http://localhost:6333/readyz](http://localhost:6333/readyz)

Stop the project while retaining PostgreSQL, Redis and Qdrant data:

```powershell
docker compose --profile rag down
```

`docker compose --profile rag down -v` also deletes the named data volumes and should only be
used when a full local reset is intended.

## Development Commands

```bash
make test
make lint
make eval
make up
make down
```

## Repository Structure

```text
app/
 ├── main.py          # FastAPI routes, workspace and API boundary
 ├── orchestrator.py  # Guarded support workflow
 ├── store.py         # PostgreSQL/SQLite durable state
 ├── retrieval.py     # BM25 + dense/Qdrant retrieval
 ├── tickets.py       # Ticket state machine
 ├── static/          # Local customer and agent workspace
 └── data/            # Versioned bundled knowledge sources

evals/                # Evaluation framework
migrations/           # Alembic schema history
tests/                # Unit, API, UI and integration tests
docs/                 # Architecture and engineering docs
```

## Engineering Status

The main feature surface includes a local operations workspace and a durable human-handoff
conversation loop. The hosted production surface still requires a real identity provider and
deployment-specific secrets.

Future improvements focus on production evidence:

- external evaluation datasets
- production SLO calibration
- outbox workflow for long-running external mutations

Adding more Agent roles is not a priority; reliability and evaluation quality are the focus.

## License

MIT
