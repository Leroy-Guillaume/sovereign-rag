"""OIDC bearer-token authentication against the operator's own IdP.

Fills the Authenticator seam documented in auth.py. The issuer is whatever
the operator configures (their Keycloak, their Entra tenant): the only
outbound calls are the discovery document and the JWKS of THAT issuer,
cached in memory and refreshed when an unknown key id shows up (standard
rotation handling). Anything that is not a well-formed, signed, unexpired
token for the configured audience answers None, which the dependency turns
into a 401; a bearer that does not even look like a JWT also answers None
so an API key can still match behind it.
"""

import time
from typing import Any, cast

import httpx
import jwt
import structlog
from fastapi import Request

from .auth import Authenticator, User
from .config import Settings

logger = structlog.get_logger()

_ALGORITHMS = ["RS256", "ES256"]
_JWKS_TTL_S = 3600.0


def _claim_path(claims: dict[str, Any], path: str) -> object:
    """Walk a dotted claim path ("realm_access.roles" for Keycloak)."""
    node: object = claims
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = cast("dict[str, object]", node).get(part)
    return node


class OidcAuth:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks: jwt.PyJWKSet | None = None
        self._fetched_at = 0.0

    async def _jwk_for(self, kid: str | None, refresh: bool) -> jwt.PyJWK | None:
        stale = time.monotonic() - self._fetched_at > _JWKS_TTL_S
        if self._jwks is None or stale or refresh:
            issuer = self._settings.oidc_issuer.rstrip("/")
            async with httpx.AsyncClient(timeout=10.0) as client:
                discovery = await client.get(f"{issuer}/.well-known/openid-configuration")
                discovery.raise_for_status()
                jwks = await client.get(discovery.json()["jwks_uri"])
                jwks.raise_for_status()
            self._jwks = jwt.PyJWKSet.from_dict(jwks.json())
            self._fetched_at = time.monotonic()
        for key in self._jwks.keys:
            if key.key_id == kid:
                return key
        return None

    async def authenticate(self, request: Request) -> User | None:
        header = request.headers.get("Authorization")
        if header is None:
            return None
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or token.count(".") != 2:
            return None
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.InvalidTokenError:
            return None
        try:
            key = await self._jwk_for(kid, refresh=False)
            if key is None:
                # Unknown kid: the IdP may have rotated; one forced refresh.
                key = await self._jwk_for(kid, refresh=True)
            if key is None:
                logger.info("oidc_unknown_kid")
                return None
        except (httpx.HTTPError, KeyError, jwt.PyJWKSetError) as exc:
            logger.warning("oidc_jwks_fetch_failed", error=str(exc))
            return None
        try:
            claims = jwt.decode(
                token,
                key=key.key,
                algorithms=_ALGORITHMS,
                audience=self._settings.oidc_audience,
                issuer=self._settings.oidc_issuer.rstrip("/"),
            )
        except jwt.InvalidTokenError as exc:
            logger.info("oidc_token_rejected", reason=type(exc).__name__)
            return None
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            return None
        raw_roles = _claim_path(claims, self._settings.oidc_roles_claim)
        is_admin = isinstance(raw_roles, list) and self._settings.oidc_admin_role in cast(
            "list[object]", raw_roles
        )
        return User(id=subject, roles=frozenset({"admin"}) if is_admin else frozenset())


class ChainAuth:
    """First authenticator that recognizes the request wins.

    Wired as [OidcAuth, ApiKeyAuth]: JWTs are settled by OIDC, opaque keys
    fall through to the constant-time API-key check, so machine access and
    the demo keys keep working next to an IdP.
    """

    def __init__(self, authenticators: list[Authenticator]) -> None:
        self._authenticators = authenticators

    async def authenticate(self, request: Request) -> User | None:
        for authenticator in self._authenticators:
            user = await authenticator.authenticate(request)
            if user is not None:
                return user
        return None
