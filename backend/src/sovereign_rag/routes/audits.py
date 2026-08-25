"""Compliance audit jobs: launch, list, inspect. Owner-scoped like documents."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from psycopg.rows import dict_row

from sovereign_rag.auth import CurrentUser
from sovereign_rag.schemas import AuditDetail, AuditLaunchIn, AuditOut

router = APIRouter(prefix="/api/audits", tags=["audits"])

_GET_DOCUMENT = """\
SELECT filename, status FROM documents d
WHERE d.id = %(id)s
  AND (d.owner_id = %(user_id)s
       OR EXISTS (SELECT 1 FROM document_permissions p
                  WHERE p.document_id = d.id AND p.principal IN (%(user_id)s, '*')))
"""

_LIST = """\
SELECT * FROM audits
WHERE owner_id = %(user_id)s
ORDER BY created_at DESC
LIMIT 50
"""

_GET = "SELECT * FROM audits WHERE id = %(id)s AND owner_id = %(user_id)s"


def _to_out(row: dict[str, Any]) -> dict[str, Any]:
    findings = row["findings"]
    return {
        **row,
        "requirements_total": len(row["requirements"]),
        "findings_done": len(findings),
        "gaps": sum(1 for f in findings if f.get("verdict") == "gap"),
    }


@router.post("", status_code=202)
async def launch_audit(request: Request, body: AuditLaunchIn, user: CurrentUser) -> AuditOut:
    pool = request.app.state.pool
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_GET_DOCUMENT, {"id": body.regulation_id, "user_id": user.id})
        document = await cur.fetchone()
    if document is None:
        # Foreign and unknown documents both answer 404: no existence oracle.
        raise HTTPException(status_code=404, detail="document not found")
    if document["status"] != "ready":
        raise HTTPException(status_code=409, detail="document is not ready")
    audit_id = await request.app.state.audits.launch(user, body.regulation_id, document["filename"])
    if audit_id is None:
        raise HTTPException(status_code=409, detail="an audit is already running")
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_GET, {"id": audit_id, "user_id": user.id})
        row = await cur.fetchone()
    assert row is not None
    return AuditOut(**_to_out(row))


@router.get("")
async def list_audits(request: Request, user: CurrentUser) -> list[AuditOut]:
    async with (
        request.app.state.pool.connection() as conn,
        conn.cursor(row_factory=dict_row) as cur,
    ):
        await cur.execute(_LIST, {"user_id": user.id})
        rows = await cur.fetchall()
    return [AuditOut(**_to_out(row)) for row in rows]


@router.get("/{audit_id}")
async def get_audit(request: Request, audit_id: UUID, user: CurrentUser) -> AuditDetail:
    async with (
        request.app.state.pool.connection() as conn,
        conn.cursor(row_factory=dict_row) as cur,
    ):
        await cur.execute(_GET, {"id": audit_id, "user_id": user.id})
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="audit not found")
    return AuditDetail(**_to_out(row))
