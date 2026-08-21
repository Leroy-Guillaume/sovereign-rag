"""Health endpoint tests: liveness, readiness aggregation, and the 10 s cache.

The health router is mounted on a bare FastAPI app here (no auth wiring at
all), which also proves the probes require no Authorization header. The full
app mounts the same router in the composition root.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport

from sovereign_rag import healthcheck
from sovereign_rag.errors import ProviderError
from sovereign_rag.routes import health


class _Probe:
    """Counts healthcheck() calls; raises ``error`` when set."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def healthcheck(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


class _OkConnection:
    async def execute(self, query: str) -> None:
        return


class _FailingConnection:
    async def execute(self, query: str) -> None:
        raise RuntimeError("connection refused")


class _StubPool:
    """Local pool stand-in; the shared FakePool lands in fakes.py in Task 16."""

    def __init__(self, failing: bool = False) -> None:
        self.calls = 0
        self._failing = failing

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[_OkConnection | _FailingConnection]:
        self.calls += 1
        yield _FailingConnection() if self._failing else _OkConnection()


def make_health_app(pool: _StubPool, llm: _Probe, embedder: _Probe) -> FastAPI:
    app = FastAPI()
    app.include_router(health.router)
    app.state.pool = pool
    app.state.llm = llm
    app.state.embedder = embedder
    return app


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_healthz_is_200_without_auth_and_without_dependencies() -> None:
    app = make_health_app(_StubPool(), _Probe(), _Probe())
    async with client_for(app) as client:
        response = await client.get("/healthz")  # no Authorization header on purpose
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_200_when_all_checks_pass() -> None:
    app = make_health_app(_StubPool(), _Probe(), _Probe())
    async with client_for(app) as client:
        response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"checks": {"database": "ok", "llm": "ok", "embeddings": "ok"}}


async def test_readyz_503_when_llm_is_down() -> None:
    app = make_health_app(_StubPool(), _Probe(error=ProviderError("ollama is down")), _Probe())
    async with client_for(app) as client:
        response = await client.get("/readyz")
    assert response.status_code == 503
    checks = response.json()["checks"]
    assert checks["database"] == "ok"
    assert checks["llm"] == "error"
    assert checks["embeddings"] == "ok"


async def test_readyz_503_when_database_is_down() -> None:
    app = make_health_app(_StubPool(failing=True), _Probe(), _Probe())
    async with client_for(app) as client:
        response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "error"


async def test_readyz_result_is_cached_for_ttl() -> None:
    pool, llm, embedder = _StubPool(), _Probe(), _Probe()
    app = make_health_app(pool, llm, embedder)
    async with client_for(app) as client:
        first = await client.get("/readyz")
        second = await client.get("/readyz")
    assert first.status_code == 200
    assert second.status_code == 200
    assert pool.calls == 1
    assert llm.calls == 1
    assert embedder.calls == 1


async def test_readyz_cache_expires_after_ttl() -> None:
    pool, llm, embedder = _StubPool(), _Probe(), _Probe()
    app = make_health_app(pool, llm, embedder)
    async with client_for(app) as client:
        await client.get("/readyz")
        # Backdate the cache entry beyond the TTL instead of sleeping 10 s.
        ts, payload, status = app.state._readyz_cache
        app.state._readyz_cache = (ts - (health.READYZ_TTL_SECONDS + 1.0), payload, status)
        await client.get("/readyz")
    assert llm.calls == 2
    assert embedder.calls == 2
    assert pool.calls == 2


@respx.mock
def test_probe_exits_0_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    respx.get("http://127.0.0.1:8000/healthz").mock(return_value=httpx.Response(200))
    assert healthcheck.main() == 0


@respx.mock
def test_probe_exits_1_on_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    respx.get("http://127.0.0.1:8000/healthz").mock(return_value=httpx.Response(503))
    assert healthcheck.main() == 1


@respx.mock
def test_probe_exits_1_when_server_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    respx.get("http://127.0.0.1:8000/healthz").mock(side_effect=httpx.ConnectError("refused"))
    assert healthcheck.main() == 1


@respx.mock
def test_probe_reads_port_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "9001")
    respx.get("http://127.0.0.1:9001/healthz").mock(return_value=httpx.Response(200))
    assert healthcheck.main() == 0
