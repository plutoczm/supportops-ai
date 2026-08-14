from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient

from app.config import Settings


class AuthenticationError(ValueError):
    pass


class AuthorizationError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    customer_id: str | None
    roles: frozenset[str]

    def require_customer(self) -> str:
        if not self.customer_id:
            raise AuthorizationError("customer_identity_required")
        return self.customer_id

    def require_agent(self) -> None:
        if not self.roles.intersection({"support_agent", "support_admin"}):
            raise AuthorizationError("support_agent_role_required")


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jwks_client = PyJWKClient(settings.auth_jwks_url) if settings.auth_jwks_url else None

    def authenticate(
        self,
        *,
        authorization: str | None,
        dev_principal_id: str | None,
        dev_customer_id: str | None,
        dev_roles: str | None,
    ) -> Principal:
        if self.settings.auth_mode == "dev":
            if not dev_principal_id:
                raise AuthenticationError("x-principal-id header required in dev auth mode")
            return Principal(
                subject=dev_principal_id,
                customer_id=dev_customer_id,
                roles=frozenset(self.parse_roles(dev_roles or "customer")),
            )

        if self.settings.auth_mode != "jwt":
            raise AuthenticationError("unsupported_auth_mode")
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthenticationError("bearer_token_required")

        payload = self.decode_jwt(authorization.removeprefix("Bearer ").strip())
        subject = str(payload.get("sub") or "")
        if not subject:
            raise AuthenticationError("token_subject_required")
        return Principal(
            subject=subject,
            customer_id=self._string_or_none(payload.get("customer_id")),
            roles=frozenset(self.parse_roles(payload.get("roles"))),
        )

    def decode_jwt(self, token: str) -> dict[str, Any]:
        if not (
            self._jwks_client
            and self.settings.auth_issuer
            and self.settings.auth_audience
        ):
            raise AuthenticationError("jwt_auth_not_configured")
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[self.settings.auth_algorithm],
                audience=self.settings.auth_audience,
                issuer=self.settings.auth_issuer,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("invalid_access_token") from exc
        return dict(payload)

    @staticmethod
    def parse_roles(value: object) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, list):
            return {str(item).strip() for item in value if str(item).strip()}
        if isinstance(value, str):
            normalized = value.replace(",", " ")
            return {item for item in normalized.split() if item}
        return set()

    @staticmethod
    def _string_or_none(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
