from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, JSONType, UTCDateTime, new_id, utcnow


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    feed_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("feed_items.id", ondelete="SET NULL"))
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    angle: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(16))
    notes: Mapped[str | None] = mapped_column(Text)
    links: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (Index("articles_tenant_state_updated_idx", "tenant_id", "state", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    slug: Mapped[str | None] = mapped_column(String(80))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    quality_score: Mapped[float | None] = mapped_column(Float)
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    published_url: Mapped[str | None] = mapped_column(Text)
    prompt_versions: Mapped[dict[str, str]] = mapped_column(JSONType, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    topic: Mapped[Topic | None] = relationship(lazy="joined")


class ArticleVersion(Base):
    __tablename__ = "article_versions"
    __table_args__ = (Index("article_versions_article_idx", "article_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), nullable=False)
    # draft | edited | seo | qa | revised | manual | restored | published
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    model_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class ResearchPack(Base):
    __tablename__ = "research_packs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")  # ok | insufficient_evidence
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # approve | reject | request_revision | force_review
    reason: Mapped[str | None] = mapped_column(Text)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
