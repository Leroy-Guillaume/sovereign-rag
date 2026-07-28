"""Document endpoints: upload (multipart), list, delete."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row

from sovereign_rag.auth import CurrentUser
from sovereign_rag.schemas import DocumentOut

router = APIRouter(prefix="/api/documents", tags=["documents"])

_EXTENSION_TO_TYPE = {".pdf": "pdf", ".docx": "docx", ".md": "md", ".txt": "txt"}

_LIST_DOCUMENTS = """\
SELECT id, filename, content_type, size_bytes, status, error, owner_id, created_at
FROM documents
ORDER BY created_at DESC
"""

_GET_DOCUMENT_OWNER = "SELECT owner_id FROM documents WHERE id = %(id)s"
_DELETE_DOCUMENT = "DELETE FROM documents WHERE id = %(id)s"


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
    row, deduplicated = await request.app.state.ingestion.ingest_upload(
        filename=filename, data=data, content_type=content_type, owner_id=user.id
    )
    out = DocumentOut(**row, deduplicated=deduplicated)
    return JSONResponse(
        status_code=200 if deduplicated else 202, content=out.model_dump(mode="json")
    )


@router.get("")
async def list_documents(request: Request, user: CurrentUser) -> list[DocumentOut]:
    # `user` gates the endpoint; listing is not filtered by owner (ACL is Phase 2).
    pool = request.app.state.pool
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_LIST_DOCUMENTS)
        rows = await cur.fetchall()
    return [DocumentOut(**row) for row in rows]


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
