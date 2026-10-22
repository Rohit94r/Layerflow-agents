"""Publishing adapter interface (plan §14.1, ADR-005)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class PublishContext:
    tenant_id: uuid.UUID
    tenant_slug: str
    article_id: uuid.UUID
    category: str
    route: str
    slug: str
    content_hash: str
    payload: dict[str, Any]
    html: str
    published_at: datetime
    site_url: str
    config: dict[str, Any]
    secrets: dict[str, str | None] = field(default_factory=dict)
    inventory_urls: list[str] = field(default_factory=list)


@dataclass
class PublishResult:
    remote_id: str
    live_url: str
    status: str = "published"
    artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifact_path: str | None = None
    preview: dict[str, Any] | None = None


class AdapterError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class PublishAdapter(Protocol):
    name: str

    async def validate(self, ctx: PublishContext) -> list[str]: ...

    async def publish(self, ctx: PublishContext, *, dry_run: bool = False) -> PublishResult: ...

    async def update(self, remote_id: str, ctx: PublishContext) -> PublishResult: ...

    async def unpublish(self, remote_id: str, ctx: PublishContext) -> None: ...

    async def health(self) -> tuple[bool, str]: ...
