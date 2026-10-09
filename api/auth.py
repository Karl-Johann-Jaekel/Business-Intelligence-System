"""OIDC bearer-token authentication (Keycloak realm `bis`) and per-endpoint scopes (plan section 10).

The API trusts only tokens that are signed by the realm (JWKS), issued by the configured issuer,
addressed to the audience `bis-api`, and unexpired. Each endpoint names the scope it needs.
With BIS_AUTH_ENABLED=false (unit tests, local tools) every request is anonymous and allowed.
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    subject: str
    username: str | None = None
    client: str | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)


ANONYMOUS = Principal(subject="anonymous")


class TokenVerifier:
    def __init__(self, issuer: str, audience: str, jwks_url: str | None = None, key=None):
        self.issuer = issuer
        self.audience = audience
        # Keys are cached and refreshed when an unknown key id shows up (Keycloak key rotation).
        self._jwks = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=600) if jwks_url else None
        self._key = key

    def decode(self, token: str) -> dict:
        """Validated claims (signature, issuer, audience, expiry); raises jwt.PyJWTError."""
        key = self._key if self._jwks is None else self._jwks.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=self.audience,
            issuer=self.issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )

    def verify(self, token: str) -> Principal:
        claims = self.decode(token)
        return Principal(
            subject=claims["sub"],
            username=claims.get("preferred_username"),
            client=claims.get("azp"),
            scopes=frozenset(claims.get("scope", "").split()),
        )


@lru_cache
def get_verifier() -> TokenVerifier | None:
    """None = authentication disabled."""
    if os.getenv("BIS_AUTH_ENABLED", "false").lower() != "true":
        return None
    issuer = os.getenv("BIS_OIDC_ISSUER")
    if not issuer:
        raise RuntimeError("BIS_AUTH_ENABLED=true requires BIS_OIDC_ISSUER")
    return TokenVerifier(
        issuer=issuer,
        audience=os.getenv("BIS_OIDC_AUDIENCE", "bis-api"),
        jwks_url=os.getenv("BIS_OIDC_JWKS_URL", f"{issuer}/protocol/openid-connect/certs"),
    )


def _unauthorized(detail: str, error: str = "invalid_token") -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": f'Bearer error="{error}"'})


def require_scope(scope: str):
    """Dependency: a valid token that carries `scope`."""

    def dependency(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
        verifier: Annotated[TokenVerifier | None, Depends(get_verifier)],
    ) -> Principal:
        if verifier is None:
            return ANONYMOUS
        if credentials is None:
            raise _unauthorized("Bearer token required", "invalid_request")
        try:
            principal = verifier.verify(credentials.credentials)
        except jwt.PyJWTError as exc:
            raise _unauthorized(f"Invalid token: {exc}") from exc
        if scope not in principal.scopes:
            raise HTTPException(
                403,
                f"Scope '{scope}' required",
                headers={"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{scope}"'},
            )
        return principal

    return dependency
