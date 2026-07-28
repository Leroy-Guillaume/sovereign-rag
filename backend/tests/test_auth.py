"""Tests for API key authentication: header parsing, key lookup, role gating."""

import httpx
from fastapi import FastAPI

from fakes import make_settings
from sovereign_rag.auth import AdminUser, ApiKeyAuth, CurrentUser


def build_app() -> FastAPI:
    """Minimal app wired exactly like main.py will be: auth on app.state."""
    app = FastAPI()
    app.state.auth = ApiKeyAuth(make_settings())

    @app.get("/protected")
    async def protected(user: CurrentUser) -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        return {"id": user.id, "roles": sorted(user.roles)}

    @app.get("/admin-only")
    async def admin_only(user: AdminUser) -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        return {"id": user.id}

    return app


def make_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_valid_key_returns_current_user() -> None:
    async with make_client(build_app()) as client:
        response = await client.get(
            "/protected", headers={"Authorization": "Bearer test-key-alice"}
        )
    assert response.status_code == 200
    assert response.json() == {"id": "alice", "roles": []}


async def test_unknown_key_is_401() -> None:
    async with make_client(build_app()) as client:
        response = await client.get(
            "/protected", headers={"Authorization": "Bearer not-a-real-key"}
        )
    assert response.status_code == 401


async def test_missing_header_is_401() -> None:
    async with make_client(build_app()) as client:
        response = await client.get("/protected")
    assert response.status_code == 401


async def test_malformed_header_is_401() -> None:
    async with make_client(build_app()) as client:
        bare = await client.get("/protected", headers={"Authorization": "test-key-alice"})
        wrong_scheme = await client.get(
            "/protected", headers={"Authorization": "Basic test-key-alice"}
        )
        empty_credentials = await client.get("/protected", headers={"Authorization": "Bearer "})
    assert bare.status_code == 401
    assert wrong_scheme.status_code == 401
    assert empty_credentials.status_code == 401


async def test_admin_key_has_admin_role() -> None:
    async with make_client(build_app()) as client:
        response = await client.get(
            "/protected", headers={"Authorization": "Bearer test-key-admin"}
        )
    assert response.status_code == 200
    assert response.json() == {"id": "admin", "roles": ["admin"]}


async def test_admin_key_reaches_admin_route() -> None:
    async with make_client(build_app()) as client:
        response = await client.get(
            "/admin-only", headers={"Authorization": "Bearer test-key-admin"}
        )
    assert response.status_code == 200
    assert response.json() == {"id": "admin"}


async def test_non_admin_key_gets_403_on_admin_route() -> None:
    async with make_client(build_app()) as client:
        response = await client.get(
            "/admin-only", headers={"Authorization": "Bearer test-key-alice"}
        )
    assert response.status_code == 403
