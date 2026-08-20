"""Admin metrics: SQL over the typed columns Phase 1 put on every message.

No metrics stack (ADR 3.12): every assistant message already carries token
counts, stage latencies, an error code and the source snapshot, so the
dashboard is three aggregate queries joinable with the audit trail by
request_id, a property Prometheus counters cannot offer.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from psycopg.rows import dict_row

from sovereign_rag.auth import AdminUser
from sovereign_rag.schemas import AdminMetricsOut, CitedDocument, LatencyOut

router = APIRouter(prefix="/api/admin", tags=["admin"])

_WINDOW_DAYS = 30

_USAGE = """\
SELECT
    count(*) FILTER (WHERE m.role = 'assistant')                    AS answers,
    count(DISTINCT m.conversation_id)                               AS conversations,
    coalesce(sum(m.prompt_tokens), 0)                               AS prompt_tokens,
    coalesce(sum(m.completion_tokens), 0)                           AS completion_tokens,
    count(*) FILTER (WHERE m.error_code IS NOT NULL)                AS errors
FROM messages m
WHERE m.created_at >= now() - make_interval(days => %(days)s)
"""

_LATENCY = """\
SELECT
    percentile_cont(0.5)  WITHIN GROUP (ORDER BY m.retrieval_ms)   AS retrieval_p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY m.retrieval_ms)   AS retrieval_p95,
    percentile_cont(0.5)  WITHIN GROUP (ORDER BY m.generation_ms)  AS generation_p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY m.generation_ms)  AS generation_p95
FROM messages m
WHERE m.role = 'assistant'
  AND m.created_at >= now() - make_interval(days => %(days)s)
"""

# The audit snapshot is the citation ledger: expanding it counts what was
# actually shown to users, deleted documents included (their snapshots
# survive by design, see COMPLIANCE A.5.28).
_TOP_CITED = """\
SELECT source ->> 'filename' AS filename, count(*) AS citations
FROM messages m
CROSS JOIN LATERAL jsonb_array_elements(m.sources) AS source
WHERE m.role = 'assistant'
  AND m.created_at >= now() - make_interval(days => %(days)s)
GROUP BY source ->> 'filename'
ORDER BY citations DESC, filename
LIMIT 5
"""


@router.get("/metrics")
async def metrics(request: Request, user: AdminUser) -> AdminMetricsOut:
    pool = request.app.state.pool
    params = {"days": _WINDOW_DAYS}
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_USAGE, params)
        usage = await cur.fetchone()
        await cur.execute(_LATENCY, params)
        latency = await cur.fetchone()
        await cur.execute(_TOP_CITED, params)
        cited = await cur.fetchall()
    assert usage is not None and latency is not None  # aggregates always yield one row

    def _ms(value: float | None) -> int | None:
        return None if value is None else int(value)

    return AdminMetricsOut(
        window_days=_WINDOW_DAYS,
        answers=usage["answers"],
        conversations=usage["conversations"],
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        errors=usage["errors"],
        retrieval=LatencyOut(
            p50_ms=_ms(latency["retrieval_p50"]), p95_ms=_ms(latency["retrieval_p95"])
        ),
        generation=LatencyOut(
            p50_ms=_ms(latency["generation_p50"]), p95_ms=_ms(latency["generation_p95"])
        ),
        top_cited=[CitedDocument(**row) for row in cited],
    )
