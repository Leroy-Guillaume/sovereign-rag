"""Append-only audit trail (COMPLIANCE A.5.28).

One helper, called from the routes on security-relevant USER actions
(uploads, deletions, sharing changes): the trail records what people did,
not what boot machinery does, so the demo seed stays out of it. The row is
written on the same connection as the action, inside its transaction: an
action that rolls back leaves no audit entry, and vice versa.
"""

from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

_INSERT = """\
INSERT INTO audit_log (actor, action, object_type, object_id, detail)
VALUES (%(actor)s, %(action)s, %(object_type)s, %(object_id)s, %(detail)s)
"""


async def audit(
    conn: AsyncConnection[Any],
    *,
    actor: str,
    action: str,
    object_type: str,
    object_id: str,
    detail: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        _INSERT,
        {
            "actor": actor,
            "action": action,
            "object_type": object_type,
            "object_id": object_id,
            "detail": Jsonb(detail or {}),
        },
    )
