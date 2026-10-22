from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, BigIntPK, JSONType, UTCDateTime, new_id, utcnow


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "jobs_claim_idx",
            "status",
            "available_at",
            "priority",
            postgresql_where=text("status = 'queued'"),
            sqlite_where=text("status = 'queued'"),
        ),
        Index("jobs_article_idx", "article_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    article_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")  # queued|running|done|failed|dead
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    locked_by: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class JobEvent(Base):
    """Human-readable progress log lines streamed to the Studio over SSE."""

    __tablename__ = "job_events"
    __table_args__ = (Index("job_events_article_idx", "article_id", "id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    article_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    target: Mapped[str] = mapped_column(String(32), nullable=False)  # ten_static | wordpress | webhook | export
    # scheduled | publishing | published | failed | cancelled | rolled_back
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="scheduled")
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    remote_id: Mapped[str | None] = mapped_column(Text)
    live_url: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)
    artifact_path: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class SocialPost(Base):
    __tablename__ = "social_posts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="linkedin")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    hook: Mapped[str | None] = mapped_column(Text)
    cta: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    image_url: Mapped[str | None] = mapped_column(Text)
    image_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    # draft | draft_ready | approved | publishing | published | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    remote_urn: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)


class ModelRun(Base):
    __tablename__ = "model_runs"
    __table_args__ = (Index("model_runs_tenant_agent_idx", "tenant_id", "agent", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    agent: Mapped[str] = mapped_column(String(64), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    article_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32))
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    output_hash: Mapped[str | None] = mapped_column(String(64))
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    repairs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("audit_log_tenant_created_idx", "tenant_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)  # user | agent | system
    actor_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class EvalCase(Base):
    __tablename__ = "eval_cases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    case_key: Mapped[str | None] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    expected: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    label: Mapped[str | None] = mapped_column(String(16))  # good | bad | edge | adversarial
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    agent: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    details: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, nullable=False, default=list)
    passed: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class SitePage(Base):
    """Own-site inventory (site='own') and competitor pages (site=<competitor key>)."""

    __tablename__ = "site_pages"
    __table_args__ = (UniqueConstraint("tenant_id", "site", "url"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    site: Mapped[str] = mapped_column(String(64), nullable=False, default="own")
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    h1: Mapped[str | None] = mapped_column(Text)
    headline: Mapped[str | None] = mapped_column(Text)
    meta_description: Mapped[str | None] = mapped_column(Text)
    canonical: Mapped[str | None] = mapped_column(Text)
    og: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    has_jsonld: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    word_count: Mapped[int | None] = mapped_column(Integer)
    headings: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    first_paragraph: Mapped[str | None] = mapped_column(Text)
    signals: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    info: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
