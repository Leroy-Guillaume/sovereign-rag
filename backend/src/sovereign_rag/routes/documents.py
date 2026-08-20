"""Document endpoints: upload (multipart), list, delete, permissions."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row

from sovereign_rag.auth import CurrentUser, User
from sovereign_rag.ingestion.service import DuplicateContentError
from sovereign_rag.schemas import DocumentOut, PermissionIn, PermissionOut

router = APIRouter(prefix="/api/documents", tags=["documents"])

_EXTENSION_TO_TYPE = {".pdf": "pdf", ".docx": "docx", ".md": "md", ".txt": "txt"}

_LIST_DOCUMENTS_ADMIN = """\
SELECT id, filename, content_type, size_bytes, status, error, owner_id, created_at
FROM documents
ORDER BY created_at DESC
"""

# Same visibility rule as retrieval (owner, named grant, or the '*' wildcard):
# what a user cannot search, they must not see listed either.
_LIST_DOCUMENTS_VISIBLE = """\
SELECT id, filename, content_type, size_bytes, status, error, owner_id, created_at
FROM documents d
WHERE d.owner_id = %(user_id)s
   OR EXISTS (SELECT 1 FROM document_permissions p
              WHERE p.document_id = d.id AND p.principal IN (%(user_id)s, '*'))
ORDER BY created_at DESC
"""

_GET_DOCUMENT_OWNER = "SELECT owner_id FROM documents WHERE id = %(id)s"
_DELETE_DOCUMENT = "DELETE FROM documents WHERE id = %(id)s"

_LIST_PERMISSIONS = """\
SELECT principal, granted_by, granted_at
FROM document_permissions
WHERE document_id = %(id)s
ORDER BY granted_at
"""

_GRANT_PERMISSION = """\
INSERT INTO document_permissions (document_id, principal, granted_by)
VALUES (%(id)s, %(principal)s, %(granted_by)s)
ON CONFLICT DO NOTHING
"""

_REVOKE_PERMISSION = """\
DELETE FROM document_permissions
WHERE document_id = %(id)s AND principal = %(principal)s
"""


@router.post("")
async def upload_document(request: Request, file: UploadFile, user: CurrentUser) -> JSONResponse:
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    content_type = _EXTENSION_TO_TYPE.get(suffix)
    if content_type is None:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported file extension {suffix!r}; allowed: pdf, docx, md, txt",
        )
    data = await file.read()
    settings = request.app.state.settings
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=422,
            detail=f"file exceeds the upload limit of {settings.max_upload_mb} MB",
        )
    try:
        row, deduplicated = await request.app.state.ingestion.ingest_upload(
            filename=filename, data=data, content_type=content_type, owner_id=user.id
        )
    except DuplicateContentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    out = DocumentOut(**row, deduplicated=deduplicated)
    return JSONResponse(
        status_code=200 if deduplicated else 202, content=out.model_dump(mode="json")
    )


@router.get("")
async def list_documents(request: Request, user: CurrentUser) -> list[DocumentOut]:
    pool = request.app.state.pool
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if "admin" in user.roles:
            await cur.execute(_LIST_DOCUMENTS_ADMIN)
        else:
            await cur.execute(_LIST_DOCUMENTS_VISIBLE, {"user_id": user.id})
        rows = await cur.fetchall()
    return [DocumentOut(**row) for row in rows]


async def _require_owner_or_admin(request: Request, document_id: UUID, user: User) -> None:
    pool = request.app.state.pool
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_GET_DOCUMENT_OWNER, {"id": document_id})
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")
    if row["owner_id"] != user.id and "admin" not in user.roles:
        raise HTTPException(
            status_code=403, detail="only the uploader or an admin can manage permissions"
        )


@router.get("/{document_id}/permissions")
async def list_permissions(
    request: Request, document_id: UUID, user: CurrentUser
) -> list[PermissionOut]:
    await _require_owner_or_admin(request, document_id, user)
    pool = request.app.state.pool
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_LIST_PERMISSIONS, {"id": document_id})
        rows = await cur.fetchall()
    return [PermissionOut(**row) for row in rows]


@router.post("/{document_id}/permissions", status_code=204)
async def grant_permission(
    request: Request, document_id: UUID, body: PermissionIn, user: CurrentUser
) -> Response:
    await _require_owner_or_admin(request, document_id, user)
    pool = request.app.state.pool
    async with pool.connection() as conn:
        await conn.execute(
            _GRANT_PERMISSION,
            {"id": document_id, "principal": body.principal, "granted_by": user.id},
        )
    return Response(status_code=204)


@router.delete("/{document_id}/permissions/{principal}", status_code=204)
async def revoke_permission(
    request: Request, document_id: UUID, principal: str, user: CurrentUser
) -> Response:
    await _require_owner_or_admin(request, document_id, user)
    pool = request.app.state.pool
    async with pool.connection() as conn:
        await conn.execute(_REVOKE_PERMISSION, {"id": document_id, "principal": principal})
    return Response(status_code=204)


@router.delete("/{document_id}", status_code=204)
async def delete_document(request: Request, document_id: UUID, user: CurrentUser) -> Response:
    pool = request.app.state.pool
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_GET_DOCUMENT_OWNER, {"id": document_id})
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")
    if row["owner_id"] != user.id and "admin" not in user.roles:
        raise HTTPException(
            status_code=403, detail="only the uploader or an admin can delete a document"
        )
    # The chunks row cascade (FK) covers pgvector; calling the store keeps
    # symmetry for stores that do not live inside Postgres.
    await request.app.state.store.delete_document(document_id)
    async with pool.connection() as conn:
        await conn.execute(_DELETE_DOCUMENT, {"id": document_id})
    return Response(status_code=204)
