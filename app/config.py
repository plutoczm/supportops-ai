from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = "sqlite:///./supportops.db"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    refund_human_review_threshold: float = 500.0

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
            llm_base_url=os.getenv("LLM_BASE_URL") or None,
            llm_api_key=os.getenv("LLM_API_KEY") or None,
            llm_model=os.getenv("LLM_MODEL") or None,
            refund_human_review_threshold=float(
                os.getenv("REFUND_HUMAN_REVIEW_THRESHOLD", "500")
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
