"""Retention (plan §7.4) and danger-zone operations. Run daily by the worker and on demand from Settings."""

from __future__ import annotations

import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.db import session_factory, utcnow
from app.models import AuditLog, FeedItem, Job, ModelRun, Publication, Session, Topic, User


async def apply_retention(tenant_id: uuid.UUID | None = None) -> dict[str, int]:
    now = utcnow()
    out: dict[str, int] = {}
    async with session_factory()() as db:
        q = update(ModelRun).where(ModelRun.created_at < now - timedelta(days=90), ModelRun.output.is_not(None)).values(output=None)
        if tenant_id:
            q = q.where(ModelRun.tenant_id == tenant_id)
        out["model_runs_trimmed"] = (await db.execute(q)).rowcount or 0

        promoted = select(Topic.feed_item_id).where(Topic.feed_item_id.is_not(None))
        q2 = delete(FeedItem).where(
            FeedItem.fetched_at < now - timedelta(days=60), FeedItem.status != "promoted", FeedItem.id.not_in(promoted)
        )
        if tenant_id:
            q2 = q2.where(FeedItem.tenant_id == tenant_id)
        out["feed_items_pruned"] = (await db.execute(q2)).rowcount or 0

        q3 = delete(Job).where(Job.status == "done", Job.finished_at < now - timedelta(days=30))
        if tenant_id:
            q3 = q3.where(Job.tenant_id == tenant_id)
        out["jobs_pruned"] = (await db.execute(q3)).rowcount or 0

        q4 = delete(AuditLog).where(AuditLog.created_at < now - timedelta(days=365))
        if tenant_id:
            q4 = q4.where(AuditLog.tenant_id == tenant_id)
        out["audit_pruned"] = (await db.execute(q4)).rowcount or 0
        out["sessions_pruned"] = (await db.execute(delete(Session).where(Session.expires_at < now))).rowcount or 0

        keep = {p for p in (await db.execute(select(Publication.artifact_path).where(Publication.status == "published"))).scalars() if p}
        await db.commit()
    removed = 0
    root = Path(get_settings().artifacts_dir)
    cutoff = time.time() - 90 * 86400
    if root.exists():
        for f in root.rglob("*.zip"):
            if str(f) not in keep and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
                removed += 1
    out["artifacts_pruned"] = removed
    return out


async def purge_feed(tenant_id: uuid.UUID, older_than_days: int) -> int:
    async with session_factory()() as db:
        promoted = select(Topic.feed_item_id).where(Topic.feed_item_id.is_not(None))
        res = await db.execute(
            delete(FeedItem).where(
                FeedItem.tenant_id == tenant_id,
                FeedItem.fetched_at < utcnow() - timedelta(days=older_than_days),
                FeedItem.status != "promoted",
                FeedItem.id.not_in(promoted),
            )
        )
        await db.commit()
        return res.rowcount or 0


async def clear_dead_jobs(tenant_id: uuid.UUID) -> int:
    async with session_factory()() as db:
        res = await db.execute(delete(Job).where(Job.tenant_id == tenant_id, Job.status.in_(("dead", "failed"))))
        await db.commit()
        return res.rowcount or 0


async def revoke_sessions(tenant_id: uuid.UUID, keep_session_id: str | None = None) -> int:
    async with session_factory()() as db:
        users = select(User.id).where(User.tenant_id == tenant_id)
        q = delete(Session).where(Session.user_id.in_(users))
        if keep_session_id:
            q = q.where(Session.id != uuid.UUID(keep_session_id))
        res = await db.execute(q)
        await db.commit()
        return res.rowcount or 0


async def run_maintenance(payload: dict[str, Any], tenant_id: uuid.UUID) -> dict[str, Any]:
    action = payload.get("action", "retention")
    if action == "retention":
        return await apply_retention(tenant_id)
    if action == "purge_feed":
        return {"deleted": await purge_feed(tenant_id, int(payload.get("older_than_days", 30)))}
    return {"skipped": action}
