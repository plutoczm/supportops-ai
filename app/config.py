from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return int(value)


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = "sqlite:///./supportops.db"
    database_auto_create_schema: bool = True
    seed_demo_data: bool = True
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    refund_human_review_threshold: float = 500.0

    knowledge_backend: str = "local"
    knowledge_sources_path: str | None = None
    embedding_backend: str = "deterministic"
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    embedding_timeout_seconds: float = 5.0
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "supportops_knowledge"
    qdrant_timeout_seconds: float = 3.0
    qdrant_sync_on_start: bool = True
    retrieval_min_evidence_score: float = 0.16
    retrieval_allow_sparse_fallback: bool = True

    auth_mode: str = "dev"
    auth_issuer: str | None = None
    auth_audience: str | None = None
    auth_jwks_url: str | None = None
    auth_algorithm: str = "RS256"

    mcp_auth_mode: str = "disabled"
    mcp_issuer_url: str | None = None
    mcp_resource_server_url: str = "http://127.0.0.1:8001/mcp"
    mcp_required_scope: str = "support:read"
    mcp_dev_customer_id: str = "CUST-001"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./supportops.db"),
            database_auto_create_schema=_env_bool("DATABASE_AUTO_CREATE_SCHEMA", True),
            seed_demo_data=_env_bool("SEED_DEMO_DATA", True),
            llm_base_url=os.getenv("LLM_BASE_URL") or None,
            llm_api_key=os.getenv("LLM_API_KEY") or None,
            llm_model=os.getenv("LLM_MODEL") or None,
            refund_human_review_threshold=float(
                os.getenv("REFUND_HUMAN_REVIEW_THRESHOLD", "500")
            ),
            knowledge_backend=os.getenv("KNOWLEDGE_BACKEND", "local").lower(),
            knowledge_sources_path=os.getenv("KNOWLEDGE_SOURCES_PATH") or None,
            embedding_backend=os.getenv("EMBEDDING_BACKEND", "deterministic").lower(),
            embedding_base_url=os.getenv("EMBEDDING_BASE_URL") or None,
            embedding_api_key=os.getenv("EMBEDDING_API_KEY") or None,
            embedding_model=os.getenv("EMBEDDING_MODEL") or None,
            embedding_dimension=_env_optional_int("EMBEDDING_DIMENSION"),
            embedding_timeout_seconds=float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "5")),
            qdrant_url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY") or None,
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "supportops_knowledge"),
            qdrant_timeout_seconds=float(os.getenv("QDRANT_TIMEOUT_SECONDS", "3")),
            qdrant_sync_on_start=_env_bool("QDRANT_SYNC_ON_START", True),
            retrieval_min_evidence_score=float(
                os.getenv("RETRIEVAL_MIN_EVIDENCE_SCORE", "0.16")
            ),
            retrieval_allow_sparse_fallback=_env_bool(
                "RETRIEVAL_ALLOW_SPARSE_FALLBACK", True
            ),
            auth_mode=os.getenv("AUTH_MODE", "dev").lower(),
            auth_issuer=os.getenv("AUTH_ISSUER") or None,
            auth_audience=os.getenv("AUTH_AUDIENCE") or None,
            auth_jwks_url=os.getenv("AUTH_JWKS_URL") or None,
            auth_algorithm=os.getenv("AUTH_ALGORITHM", "RS256"),
            mcp_auth_mode=os.getenv("MCP_AUTH_MODE", "disabled").lower(),
            mcp_issuer_url=os.getenv("MCP_ISSUER_URL") or None,
            mcp_resource_server_url=os.getenv(
                "MCP_RESOURCE_SERVER_URL", "http://127.0.0.1:8001/mcp"
            ),
            mcp_required_scope=os.getenv("MCP_REQUIRED_SCOPE", "support:read"),
            mcp_dev_customer_id=os.getenv("MCP_DEV_CUSTOMER_ID", "CUST-001"),
        )

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)

    @property
    def production_embeddings_enabled(self) -> bool:
        return self.embedding_backend == "openai" and bool(
            self.embedding_base_url and self.embedding_model
        )
