"""Audit trail helper. Every state transition and user action writes one row."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def audit(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_type: str,
    actor_id: str | uuid.UUID | None,
    action: str,
    entity: str,
    entity_id: str | uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    row = AuditLog(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=str(actor_id) if actor_id is not None else None,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        detail=detail,
    )
    db.add(row)
    return row
