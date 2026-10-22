"""Postgres table queue (ADR-001): claim with FOR UPDATE SKIP LOCKED, retries with backoff,
visibility-timeout recovery. On SQLite the same code runs; the conditional UPDATE guarantees one claimer."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_factory, utcnow
from app.models import Job, JobEvent

MODEL_LANE = frozenset({"research", "write", "edit", "seo", "qa", "social", "eval"})
IO_LANE = frozenset({"discover", "publish", "distribute", "crawl_inventory", "crawl_competitors", "maintenance"})
JOB_TYPES = MODEL_LANE | IO_LANE

DEFAULT_PRIORITY = {
    "publish": 10,
    "distribute": 20,
    "research": 50,
    "write": 50,
    "edit": 50,
    "seo": 50,
    "qa": 50,
    "social": 60,
    "discover": 100,
    "crawl_inventory": 150,
    "crawl_competitors": 160,
    "eval": 200,
    "maintenance": 250,
}
BACKOFF_S = (30, 120, 600)
ACTIVE_STATUSES = ("queued", "running")


class JobError(Exception):
    """Base for failures raised by job handlers."""

    retryable = True

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class RetryableError(JobError):
    retryable = True


class PermanentError(JobError):
    retryable = False


async def enqueue(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    type: str,
    payload: dict[str, Any] | None = None,
    article_id: uuid.UUID | None = None,
    priority: int | None = None,
    max_attempts: int = 3,
    available_at: datetime | None = None,
    created_by: uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> Job:
    """Add a job. If an identical active job exists (same type + article/dedupe key) it is returned instead,
    so double clicks never create duplicate work."""
    if type not in JOB_TYPES:
        raise ValueError(f"Unknown job type {type}")
    payload = dict(payload or {})
    if dedupe_key:
        payload["dedupe_key"] = dedupe_key
    existing_q = select(Job).where(Job.tenant_id == tenant_id, Job.type == type, Job.status.in_(ACTIVE_STATUSES))
    if article_id is not None:
        existing_q = existing_q.where(Job.article_id == article_id)
        existing = (await db.execute(existing_q.limit(1))).scalar_one_or_none()
        if existing is not None:
            return existing
    elif dedupe_key:
        for job in (await db.execute(existing_q)).scalars():
            if (job.payload or {}).get("dedupe_key") == dedupe_key:
                return job
    job = Job(
        tenant_id=tenant_id,
        type=type,
        article_id=article_id,
        payload=payload,
        priority=priority if priority is not None else DEFAULT_PRIORITY.get(type, 100),
        max_attempts=max_attempts,
        available_at=available_at or utcnow(),
        created_by=created_by,
    )
    db.add(job)
    await db.flush()
    return job


async def claim(db: AsyncSession, worker_id: str, types: frozenset[str] | set[str]) -> Job | None:
    for _ in range(5):
        now = utcnow()
        candidate = (
            await db.execute(
                select(Job.id)
                .where(Job.status == "queued", Job.available_at <= now, Job.type.in_(sorted(types)))
                .order_by(Job.priority.asc(), Job.available_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if candidate is None:
            await db.rollback()
            return None
        res = await db.execute(
            update(Job)
            .where(Job.id == candidate, Job.status == "queued")
            .values(
                status="running",
                locked_at=now,
                locked_by=worker_id,
                attempts=Job.attempts + 1,
                started_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if res.rowcount == 1:
            await db.commit()
            return await db.get(Job, candidate, populate_existing=True)
        await db.rollback()
    return None


async def heartbeat(job_id: uuid.UUID, worker_id: str) -> None:
    async with session_factory()() as db:
        await db.execute(
            update(Job)
            .where(Job.id == job_id, Job.locked_by == worker_id, Job.status == "running")
            .values(locked_at=utcnow())
        )
        await db.commit()


async def complete(db: AsyncSession, job: Job, result: dict[str, Any] | None = None) -> None:
    job.status = "done"
    job.result = result or {}
    job.finished_at = utcnow()
    job.locked_at = None
    job.last_error = None
    await db.commit()


async def fail(db: AsyncSession, job: Job, error: str, *, retryable: bool = True, retry_after_s: float | None = None) -> str:
    """Record a failure. Returns the new status: queued (will retry), failed (no retry) or dead (exhausted)."""
    job.last_error = error[:4000]
    job.locked_at = None
    job.locked_by = None
    if retryable and job.attempts < job.max_attempts:
        delay = retry_after_s if retry_after_s is not None else BACKOFF_S[min(job.attempts - 1, len(BACKOFF_S) - 1)]
        job.status = "queued"
        job.available_at = utcnow() + timedelta(seconds=delay)
    else:
        job.status = "dead" if retryable else "failed"
        job.finished_at = utcnow()
    await db.commit()
    return job.status


async def requeue_stale(db: AsyncSession, visibility_timeout_s: int) -> list[Job]:
    """Jobs whose worker stopped heart-beating are put back on the queue (or marked dead if exhausted)."""
    cutoff = utcnow() - timedelta(seconds=visibility_timeout_s)
    stale = (
        (await db.execute(select(Job).where(Job.status == "running", or_(Job.locked_at.is_(None), Job.locked_at < cutoff))))
        .scalars()
        .all()
    )
    for job in stale:
        job.last_error = f"Worker {job.locked_by or '?'} stopped responding (visibility timeout); re-queued"
        job.locked_by = None
        job.locked_at = None
        if job.attempts < job.max_attempts:
            job.status = "queued"
            job.available_at = utcnow()
        else:
            job.status = "dead"
            job.finished_at = utcnow()
    if stale:
        await db.commit()
    return list(stale)


async def retry(db: AsyncSession, job: Job) -> Job:
    job.status = "queued"
    job.attempts = 0
    job.available_at = utcnow()
    job.finished_at = None
    job.locked_at = None
    job.locked_by = None
    await db.flush()
    return job


async def log_event(
    tenant_id: uuid.UUID,
    message: str,
    *,
    job_id: uuid.UUID | None = None,
    article_id: uuid.UUID | None = None,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    """Write a progress line in its own short transaction so the Studio sees it immediately."""
    async with session_factory()() as db:
        db.add(JobEvent(tenant_id=tenant_id, job_id=job_id, article_id=article_id, level=level, message=message, data=data))
        await db.commit()


async def queue_stats(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    rows = (
        await db.execute(select(Job.status, func.count()).where(Job.tenant_id == tenant_id).group_by(Job.status))
    ).all()
    counts = {status: n for status, n in rows}
    since = utcnow() - timedelta(hours=24)
    failed_24h = (
        await db.execute(
            select(func.count()).where(
                Job.tenant_id == tenant_id,
                Job.status.in_(("failed", "dead")),
                Job.finished_at >= since,
            )
        )
    ).scalar_one()
    retrying = (
        await db.execute(
            select(func.count()).where(
                Job.tenant_id == tenant_id, Job.status == "queued", Job.attempts > 0, Job.last_error.is_not(None)
            )
        )
    ).scalar_one()
    oldest = (
        await db.execute(
            select(func.min(Job.available_at)).where(
                and_(Job.tenant_id == tenant_id, Job.status == "queued", Job.available_at <= utcnow())
            )
        )
    ).scalar_one()
    age = None
    if oldest is not None:
        if oldest.tzinfo is None:
            from datetime import UTC

            oldest = oldest.replace(tzinfo=UTC)
        age = int((utcnow() - oldest).total_seconds())
    return {
        "queued": counts.get("queued", 0),
        "running": counts.get("running", 0),
        "done": counts.get("done", 0),
        "failed": counts.get("failed", 0),
        "dead": counts.get("dead", 0),
        "retrying": retrying,
        "failed_24h": failed_24h,
        "oldest_queued_age_s": age,
    }
