from __future__ import annotations

from dataclasses import dataclass

from app.auth import AuthService
from app.config import Settings
from app.guardrails import InputGuardrails
from app.knowledge import KnowledgeService, default_knowledge_documents
from app.model_gateway import OpenAICompatibleModel
from app.orchestrator import SupportOrchestrator
from app.policy import ActionPolicy
from app.retrieval import (
    BM25Retriever,
    DeterministicHashEmbedding,
    HybridRetriever,
    InMemoryDenseRetriever,
    OpenAICompatibleEmbedding,
    QdrantDenseRetriever,
)
from app.router import IntentRouter
from app.store import SupportStore
from app.tickets import TicketWorkflow
from app.tools import SupportTools


@dataclass(slots=True)
class ServiceContainer:
    settings: Settings
    auth: AuthService
    store: SupportStore
    tickets: TicketWorkflow
    tools: SupportTools
    knowledge: KnowledgeService
    orchestrator: SupportOrchestrator


def build_container(settings: Settings | None = None) -> ServiceContainer:
    settings = settings or Settings.from_env()
    store = SupportStore(settings.database_url)
    if settings.database_auto_create_schema:
        store.create_schema()
    if settings.seed_demo_data:
        store.seed_demo_data()

    model = None
    if settings.llm_enabled:
        model = OpenAICompatibleModel(
            base_url=settings.llm_base_url or "",
            model=settings.llm_model or "",
            api_key=settings.llm_api_key,
        )

    documents = default_knowledge_documents()
    if settings.embedding_backend == "deterministic":
        embedding_provider = DeterministicHashEmbedding()
    elif settings.production_embeddings_enabled:
        embedding_provider = OpenAICompatibleEmbedding(
            base_url=settings.embedding_base_url or "",
            model=settings.embedding_model or "",
            api_key=settings.embedding_api_key,
            dimension=settings.embedding_dimension,
        )
    else:
        raise ValueError(
            "EMBEDDING_BACKEND=openai requires EMBEDDING_BASE_URL and EMBEDDING_MODEL"
        )

    if settings.knowledge_backend == "local":
        dense_retriever = InMemoryDenseRetriever(documents, embedding_provider)
    elif settings.knowledge_backend == "qdrant":
        if settings.embedding_backend != "openai":
            raise ValueError(
                "KNOWLEDGE_BACKEND=qdrant requires EMBEDDING_BACKEND=openai; "
                "the deterministic embedding is CI/local-only"
            )
        dense_retriever = QdrantDenseRetriever(
            documents,
            embedding_provider,
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            collection=settings.qdrant_collection,
        )
    else:
        raise ValueError("KNOWLEDGE_BACKEND must be 'local' or 'qdrant'")

    retriever = HybridRetriever(
        documents,
        dense_retriever=dense_retriever,
        sparse_retriever=BM25Retriever(documents),
    )

    auth = AuthService(settings)
    guardrails = InputGuardrails()
    router = IntentRouter(model=model)
    knowledge = KnowledgeService(
        model=model,
        documents=documents,
        retriever=retriever,
        min_evidence_score=settings.retrieval_min_evidence_score,
    )
    policy = ActionPolicy(settings.refund_human_review_threshold)
    tickets = TicketWorkflow(store)
    tools = SupportTools(store, tickets)
    orchestrator = SupportOrchestrator(
        store=store,
        guardrails=guardrails,
        router=router,
        knowledge=knowledge,
        policy=policy,
        tools=tools,
    )
    return ServiceContainer(
        settings=settings,
        auth=auth,
        store=store,
        tickets=tickets,
        tools=tools,
        knowledge=knowledge,
        orchestrator=orchestrator,
    )
