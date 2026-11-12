"""Audit trail writer (spec section 4.8). Callers own the transaction boundary."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_actor
from app.core.serialization import jsonable
from app.modules.audit.models import AuditLog


def write_audit(
    session: AsyncSession,
    *,
    household_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    actor: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        household_id=household_id,
        actor=actor or get_actor(),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_data=jsonable(before) if before is not None else None,
        after_data=jsonable(after) if after is not None else None,
    )
    session.add(entry)
    return entry
