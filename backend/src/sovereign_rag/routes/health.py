"""Liveness and readiness probes.

``/healthz`` answers 200 unconditionally (the process is up); ``/readyz``
checks the database and both providers individually and caches the aggregate
for 10 seconds so orchestrator probes do not hammer Ollama or the embedding
model. Neither route requires authentication: Docker HEALTHCHECK and load
balancers cannot send API keys.
"""

import time

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

logger = structlog.get_logger(__name__)

READYZ_TTL_SECONDS = 10.0

type ReadyzCache = tuple[float, dict[str, dict[str, str]], int]


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe: no dependencies, must never touch the DB or providers."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness probe: DB + LLM + embeddings, individually reported, cached."""
    state = request.app.state
    now = time.monotonic()
    cached: ReadyzCache | None = getattr(state, "_readyz_cache", None)
    if cached is not None and now - cached[0] < READYZ_TTL_SECONDS:
        return JSONResponse(cached[1], status_code=cached[2])

    # The probe is anonymous by design (orchestrators cannot authenticate),
    # so it reports WHICH dependency failed but never the raw exception:
    # connection strings, hostnames and provider payloads belong in the logs.
    checks: dict[str, str] = {}
    try:
        async with state.pool.connection() as conn:
            await conn.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        logger.warning("readyz_database_failed", exc_info=True)
        checks["database"] = "error"
    try:
        await state.llm.healthcheck()
        checks["llm"] = "ok"
    except Exception:
        logger.warning("readyz_llm_failed", exc_info=True)
        checks["llm"] = "error"
    try:
        await state.embedder.healthcheck()
        checks["embeddings"] = "ok"
    except Exception:
        logger.warning("readyz_embeddings_failed", exc_info=True)
        checks["embeddings"] = "error"

    status_code = 200 if all(value == "ok" for value in checks.values()) else 503
    payload = {"checks": checks}
    state._readyz_cache = (now, payload, status_code)
    return JSONResponse(payload, status_code=status_code)
