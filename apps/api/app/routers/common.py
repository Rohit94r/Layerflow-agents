"""Small helpers shared by routers."""

from __future__ import annotations

import uuid
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found

T = TypeVar("T")


def parse_id(value: str, entity: str = "resource") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise ApiError(404, "not_found", f"{entity.capitalize()} not found") from exc


async def owned(db: AsyncSession, model: type[T], id_: str | uuid.UUID, tenant_id: uuid.UUID, entity: str) -> T:
    oid = id_ if isinstance(id_, uuid.UUID) else parse_id(id_, entity)
    row = await db.get(model, oid)
    if row is None or getattr(row, "tenant_id", None) != tenant_id:
        raise not_found(entity)
    return row


def page_params(page: int, page_size: int, max_size: int = 200) -> tuple[int, int, int]:
    page = max(1, page)
    page_size = max(1, min(max_size, page_size))
    return page, page_size, (page - 1) * page_size


def paginated(items: list[Any], total: int, page: int, page_size: int) -> dict[str, Any]:
    return {"items": items, "total": total, "page": page, "page_size": page_size}
