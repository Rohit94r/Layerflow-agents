from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, JSONType, UTCDateTime, new_id, utcnow


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("tenant_id", "url"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # rss | gdelt | edgar | ir | hn | reddit | manual
    name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    region: Mapped[str | None] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_item_count: Mapped[int | None] = mapped_column(Integer)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class FeedItem(Base):
    __tablename__ = "feed_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "canonical_url"),
        Index("feed_items_tenant_published_idx", "tenant_id", "published_at"),
        Index("feed_items_tenant_status_score_idx", "tenant_id", "status", "score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    lang: Mapped[str | None] = mapped_column(String(8))
    entities: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, nullable=False, default=list)
    region: Mapped[str | None] = mapped_column(String(16))
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    score_breakdown: Mapped[dict[str, float]] = mapped_column(JSONType, nullable=False, default=dict)
    suggested_category: Mapped[str | None] = mapped_column(String(32))
    category_reason: Mapped[str | None] = mapped_column(Text)
    why_it_matters: Mapped[str | None] = mapped_column(Text)
    title_fingerprint: Mapped[str | None] = mapped_column(String(16))
    dedupe_cluster_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_cluster_head: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    embedding: Mapped[list[float] | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    ignored_reason: Mapped[str | None] = mapped_column(Text)

    source: Mapped[Source | None] = relationship(lazy="joined")
