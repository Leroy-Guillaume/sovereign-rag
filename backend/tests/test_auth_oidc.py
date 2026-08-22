"""OIDC bearer auth: validation, roles, rotation, coexistence with API keys."""

import os
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import jwt
import respx
from cryptography.hazmat.primitives.asymmetric import rsa

from fakes import FakeEmbedding, FakeLLM, InMemoryVectorStore, make_settings

ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag_test"
)

ISSUER = "https://idp.test/realms/acme"
AUDIENCE = "sovereign-rag"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_ROGUE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    from jwt.algorithms import RSAAlgorithm

    public = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {**public, "kid": kid, "alg": "RS256", "use": "sig"}


def _token(
    key: rsa.RSAPrivateKey = _KEY,
    kid: str = "k1",
    **overrides: Any,
) -> str:
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "guillaume",
        "exp": int(time.time()) + 300,
        "roles": [],
    }
    claims.update(overrides)
    from cryptography.hazmat.primitives import serialization

    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})


def _mock_idp(jwks: dict[str, Any]) -> None:
    respx.get(f"{ISSUER}/.well-known/openid-configuration").respond(
        json={"jwks_uri": f"{ISSUER}/jwks"}
    )
    respx.get(f"{ISSUER}/jwks").respond(json=jwks)


def _client(api_client: ClientFactory, **settings_overrides: Any):
    return api_client(
        settings=make_settings(
            database_url=TEST_DATABASE_URL,
            oidc_issuer=ISSUER,
            oidc_audience=AUDIENCE,
            **settings_overrides,
        ),
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
    )


@respx.mock
async def test_valid_token_authenticates_and_maps_roles(api_client: ClientFactory, pg: Any) -> None:
    _mock_idp({"keys": [_jwk(_KEY, "k1")]})
    async with _client(api_client) as client:
        me = await client.get(
            "/api/me", headers={"Authorization": f"Bearer {_token(roles=['reader'])}"}
        )
        assert me.status_code == 200
        assert me.json() == {"id": "guillaume", "roles": []}
        admin = await client.get(
            "/api/me", headers={"Authorization": f"Bearer {_token(roles=['admin'])}"}
        )
        assert admin.json()["roles"] == ["admin"]


@respx.mock
async def test_nested_roles_claim_keycloak_style(api_client: ClientFactory, pg: Any) -> None:
    _mock_idp({"keys": [_jwk(_KEY, "k1")]})
    async with _client(api_client, oidc_roles_claim="realm_access.roles") as client:
        token = _token(realm_access={"roles": ["admin"]})
        me = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert me.json()["roles"] == ["admin"]


@respx.mock
async def test_bad_tokens_are_rejected(api_client: ClientFactory, pg: Any) -> None:
    _mock_idp({"keys": [_jwk(_KEY, "k1")]})
    async with _client(api_client) as client:
        for token in (
            _token(exp=int(time.time()) - 60),  # expired
            _token(aud="someone-else"),  # wrong audience
            _token(iss="https://evil.test"),  # wrong issuer
            _token(key=_ROGUE, kid="k1"),  # wrong signature under a known kid
            "not.a.jwt",
        ):
            resp = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 401, token


@respx.mock
async def test_unknown_kid_triggers_one_jwks_refresh(api_client: ClientFactory, pg: Any) -> None:
    """Key rotation: the first JWKS has no k2; the refetch finds it."""
    respx.get(f"{ISSUER}/.well-known/openid-configuration").respond(
        json={"jwks_uri": f"{ISSUER}/jwks"}
    )
    jwks_route = respx.get(f"{ISSUER}/jwks")
    jwks_route.side_effect = [
        httpx.Response(200, json={"keys": [_jwk(_ROGUE, "old")]}),
        httpx.Response(200, json={"keys": [_jwk(_ROGUE, "old"), _jwk(_KEY, "k2")]}),
    ]
    async with _client(api_client) as client:
        me = await client.get("/api/me", headers={"Authorization": f"Bearer {_token(kid='k2')}"})
        assert me.status_code == 200
        assert jwks_route.call_count == 2


@respx.mock
async def test_api_keys_still_work_next_to_oidc(api_client: ClientFactory, pg: Any) -> None:
    _mock_idp({"keys": [_jwk(_KEY, "k1")]})
    async with _client(api_client) as client:
        me = await client.get("/api/me", headers={"Authorization": "Bearer test-key-alice"})
        assert me.status_code == 200
        assert me.json()["id"] == "alice"


async def test_auth_config_is_public_and_reflects_settings(
    api_client: ClientFactory, pg: Any
) -> None:
    async with _client(api_client, oidc_client_id="sovereign-rag-spa") as client:
        resp = await client.get("/api/auth/config")  # no Authorization header
        assert resp.status_code == 200
        assert resp.json() == {"oidc": {"issuer": ISSUER, "client_id": "sovereign-rag-spa"}}
    async with _client(api_client) as client:  # no client id configured
        assert (await client.get("/api/auth/config")).json() == {"oidc": None}
