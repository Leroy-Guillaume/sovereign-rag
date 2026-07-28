"""Request authentication: turn an HTTP request into a User.

Routes only ever depend on CurrentUser / AdminUser. The Authenticator
Protocol is the seam for OIDC (Phase 2) and Entra ID (Phase 4): swap the
implementation stored on app.state.auth, the routes never change.
"""

import secrets
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request

from .config import Settings


@dataclass(frozen=True, slots=True)
class User:
    id: str
    roles: frozenset[str]  # {"admin"} or empty -- gates the admin surface


class Authenticator(Protocol):
    async def authenticate(self, request: Request) -> User | None: ...  # None -> HTTP 401


class ApiKeyAuth:
    """Maps `Authorization: Bearer <key>` to a user via settings.auth_api_keys.

    Constant-time by construction: iterates EVERY configured key and calls
    secrets.compare_digest on each, with no early exit -- never a dict lookup
    keyed by the candidate, so response time does not reveal which (or
    whether a) key matched.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def authenticate(self, request: Request) -> User | None:
        header = request.headers.get("Authorization")
        if header is None:
            return None
        scheme, _, candidate = header.partition(" ")
        if scheme.lower() != "bearer" or not candidate:
            return None
        candidate_bytes = candidate.encode("utf-8")
        matched: str | None = None
        for key, user_id in self._settings.auth_api_keys.items():
            if secrets.compare_digest(candidate_bytes, key.encode("utf-8")):
                matched = user_id
        if matched is None:
            return None
        is_admin = matched in self._settings.auth_admin_users
        return User(id=matched, roles=frozenset({"admin"}) if is_admin else frozenset())


async def get_current_user(request: Request) -> User:
    """Single auth dependency: delegates to whatever Authenticator main.py wired."""
    authenticator: Authenticator = request.app.state.auth
    user = await authenticator.authenticate(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
