from __future__ import annotations

from dataclasses import dataclass

from app.auth import AuthService
from app.config import Settings
from app.guardrails import InputGuardrails
from app.knowledge import KnowledgeService, default_knowledge_documents
from app.model_gateway import OpenAICompatibleModel
from app.orchestrator import SupportOrchestrator
from app.policy import ActionPolicy
from app.reliability import LocalReliabilityCoordinator, RedisReliabilityCoordinator
from app.retrieval import (
    BM25Retriever,
    DeterministicHashEmbedding,
    HybridRetriever,
    InMemoryDenseRetriever,
    OpenAICompatibleEmbedding,
    QdrantDenseRetriever,
    RetrievalBackendError,
    UnavailableDenseRetriever,
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
    reliability: LocalReliabilityCoordinator | RedisReliabilityCoordinator
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

    if settings.reliability_backend == "local":
        reliability = LocalReliabilityCoordinator()
    elif settings.reliability_backend == "redis":
        reliability = RedisReliabilityCoordinator(
            url=settings.redis_url,
            socket_timeout_seconds=settings.redis_socket_timeout_seconds,
            key_prefix=settings.redis_key_prefix,
        )
        if settings.reliability_require_startup:
            reliability.ping()
    else:
        raise ValueError("RELIABILITY_BACKEND must be 'local' or 'redis'")

    model = None
    if settings.llm_enabled:
        model = OpenAICompatibleModel(
            base_url=settings.llm_base_url or "",
            model=settings.llm_model or "",
            api_key=settings.llm_api_key,
        )

    documents = default_knowledge_documents(settings.knowledge_sources_path)
    if settings.embedding_backend == "deterministic":
        embedding_provider = DeterministicHashEmbedding()
    elif settings.production_embeddings_enabled:
        embedding_provider = OpenAICompatibleEmbedding(
            base_url=settings.embedding_base_url or "",
            model=settings.embedding_model or "",
            api_key=settings.embedding_api_key,
            dimension=settings.embedding_dimension,
            timeout_seconds=settings.embedding_timeout_seconds,
        )
    else:
        raise ValueError(
            "EMBEDDING_BACKEND=openai requires EMBEDDING_BASE_URL and EMBEDDING_MODEL"
        )

    try:
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
                timeout_seconds=settings.qdrant_timeout_seconds,
                sync_on_start=settings.qdrant_sync_on_start,
            )
        else:
            raise ValueError("KNOWLEDGE_BACKEND must be 'local' or 'qdrant'")
    except RetrievalBackendError as exc:
        if not settings.retrieval_allow_sparse_fallback:
            raise
        dense_retriever = UnavailableDenseRetriever(exc)

    retriever = HybridRetriever(
        documents,
        dense_retriever=dense_retriever,
        sparse_retriever=BM25Retriever(documents),
        allow_sparse_fallback=settings.retrieval_allow_sparse_fallback,
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
        reliability=reliability,
        action_confirmation_ttl_seconds=settings.action_confirmation_ttl_seconds,
        action_lock_ttl_seconds=settings.action_lock_ttl_seconds,
        fail_closed_mutations=settings.reliability_fail_closed_mutations,
    )
    return ServiceContainer(
        settings=settings,
        auth=auth,
        store=store,
        reliability=reliability,
        tickets=tickets,
        tools=tools,
        knowledge=knowledge,
        orchestrator=orchestrator,
    )
