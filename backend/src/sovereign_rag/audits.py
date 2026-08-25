"""Compliance audit jobs: launch, checkpoint, resume.

The audits row is the checkpoint. The graph calls back after the
cartographer (requirements persisted) and after every judged requirement
(finding appended), so a process restart resumes at the first unevaluated
requirement: resume_interrupted() is called from the lifespan and simply
relaunches whatever was queued or running. One audit at a time per owner:
these are long local-LLM jobs, not a queueing system.
"""

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from .agents.compliance import (
    AuditDeps,
    AuditState,
    Finding,
    Requirement,
    build_audit_graph,
)
from .audit import audit as audit_event
from .auth import User
from .config import Settings
from .embeddings.base import EmbeddingClient
from .llm.base import LLMClient
from .store.base import VectorStore

logger = structlog.get_logger()

_INSERT = """\
INSERT INTO audits (id, owner_id, regulation_id, regulation_filename)
VALUES (%(id)s, %(owner_id)s, %(regulation_id)s, %(filename)s)
"""

_HAS_ACTIVE = """\
SELECT 1 FROM audits
WHERE owner_id = %(owner_id)s AND status IN ('queued', 'running')
"""

_LOAD = "SELECT * FROM audits WHERE id = %(id)s"

_REGULATION_CHUNKS = """\
SELECT content FROM chunks WHERE document_id = %(id)s ORDER BY chunk_index
"""

_SET_STATUS = "UPDATE audits SET status = %(status)s, error = %(error)s WHERE id = %(id)s"

_SET_REQUIREMENTS = "UPDATE audits SET requirements = %(requirements)s WHERE id = %(id)s"

_APPEND_FINDING = """\
UPDATE audits SET findings = findings || %(finding)s::jsonb WHERE id = %(id)s
"""

_COMPLETE = """\
UPDATE audits
SET status = 'completed', summary = %(summary)s, completed_at = now()
WHERE id = %(id)s
"""

_INTERRUPTED = "SELECT id, owner_id FROM audits WHERE status IN ('queued', 'running')"


class AuditService:
    def __init__(
        self,
        pool: AsyncConnectionPool,
        llm: LLMClient,
        embedder: EmbeddingClient,
        store: VectorStore,
        settings: Settings,
    ) -> None:
        self._pool = pool
        self._llm = llm
        self._embedder = embedder
        self._store = store
        self._settings = settings
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    async def launch(
        self, user: User, regulation_id: UUID, regulation_filename: str
    ) -> UUID | None:
        """Create and start an audit; None when one is already active."""
        audit_id = uuid4()
        async with self._pool.connection() as conn:
            cur = await conn.execute(_HAS_ACTIVE, {"owner_id": user.id})
            if await cur.fetchone() is not None:
                return None
            await conn.execute(
                _INSERT,
                {
                    "id": audit_id,
                    "owner_id": user.id,
                    "regulation_id": regulation_id,
                    "filename": regulation_filename,
                },
            )
            await audit_event(
                conn,
                actor=user.id,
                action="audit.start",
                object_type="audit",
                object_id=str(audit_id),
                detail={"regulation": regulation_filename},
            )
        self._start_task(audit_id, user.id)
        return audit_id

    def _start_task(self, audit_id: UUID, owner_id: str) -> None:
        task = asyncio.create_task(self._run(audit_id, owner_id))
        self._tasks[audit_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(audit_id, None))

    async def resume_interrupted(self) -> int:
        """Relaunch queued/running audits after a restart; the per-requirement
        checkpoints make this cheap. Returns how many were resumed."""
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_INTERRUPTED)
            rows = await cur.fetchall()
        for row in rows:
            self._start_task(row["id"], row["owner_id"])
        if rows:
            logger.info("audits_resumed", count=len(rows))
        return len(rows)

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()

    async def _run(self, audit_id: UUID, owner_id: str) -> None:
        user = User(id=owner_id, roles=frozenset())
        try:
            async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(_LOAD, {"id": audit_id})
                row = await cur.fetchone()
                if row is None:
                    return
                await cur.execute(_REGULATION_CHUNKS, {"id": row["regulation_id"]})
                chunks = [r["content"] for r in await cur.fetchall()]
                await conn.execute(
                    _SET_STATUS, {"id": audit_id, "status": "running", "error": None}
                )

            async def on_requirements(requirements: list[Requirement]) -> None:
                async with self._pool.connection() as conn:
                    await conn.execute(
                        _SET_REQUIREMENTS,
                        {"id": audit_id, "requirements": Jsonb(requirements)},
                    )

            async def on_finding(finding: Finding) -> None:
                async with self._pool.connection() as conn:
                    await conn.execute(
                        _APPEND_FINDING,
                        {"id": audit_id, "finding": json.dumps([finding])},
                    )

            deps = AuditDeps(
                llm=self._llm,
                embedder=self._embedder,
                store=self._store,
                settings=self._settings,
                user=user,
                on_requirements=on_requirements,
                on_finding=on_finding,
            )
            graph = build_audit_graph(deps)
            state = AuditState(
                regulation_id=str(row["regulation_id"]),
                regulation_text=chunks,
                requirements=row["requirements"],
                findings=row["findings"],
                summary="",
            )
            final: dict[str, Any] = await graph.ainvoke(state)
            async with self._pool.connection() as conn:
                await conn.execute(_COMPLETE, {"id": audit_id, "summary": final["summary"]})
                await audit_event(
                    conn,
                    actor=owner_id,
                    action="audit.complete",
                    object_type="audit",
                    object_id=str(audit_id),
                    detail={"findings": len(final["findings"])},
                )
        except asyncio.CancelledError:
            # Process shutdown mid-run: the row stays 'running' and the next
            # boot resumes it from its checkpoints. That is the design.
            raise
        except Exception as exc:
            logger.exception("audit_failed", audit_id=str(audit_id))
            async with self._pool.connection() as conn:
                await conn.execute(
                    _SET_STATUS,
                    {"id": audit_id, "status": "failed", "error": str(exc)[:500]},
                )
