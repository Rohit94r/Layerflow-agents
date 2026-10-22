"""A7 Scheduler — deterministic, timezone-aware (DST-safe via zoneinfo). Cadence guard: N per day, slot times,
weekdays only, max per category per day, avoid same category back-to-back when alternatives exist.
A missed window (worker down) is published exactly once on recovery and flagged late."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.models import Article, Publication, Tenant
from app.queue.jobs import enqueue


def _slots(cadence: dict[str, Any]) -> list[time]:
    out = []
    for s in cadence.get("slots") or ["08:30"]:
        try:
            hh, mm = s.split(":")
            out.append(time(int(hh), int(mm)))
        except ValueError:
            continue
    return sorted(out) or [time(8, 30)]


def next_slot(
    *,
    cadence: dict[str, Any],
    timezone: str,
    category: str,
    taken: list[tuple[datetime, str]],
    now: datetime | None = None,
    horizon_days: int = 30,
) -> tuple[datetime, str]:
    tz = ZoneInfo(timezone)
    now = now or utcnow()
    local_now = now.astimezone(tz)
    per_day = int(cadence.get("per_day", 2))
    max_cat = int(cadence.get("max_per_category_per_day", 1))
    weekdays_only = bool(cadence.get("weekdays_only", True))
    taken_local = sorted((t.astimezone(tz), c) for t, c in taken)
    slot_times = _slots(cadence)
    for d in range(horizon_days):
        day = (local_now + timedelta(days=d)).date()
        if weekdays_only and day.weekday() >= 5:
            continue
        same_day = [(t, c) for t, c in taken_local if t.date() == day]
        if len(same_day) >= per_day:
            continue
        if sum(1 for _, c in same_day if c == category) >= max_cat:
            continue
        for st in slot_times:
            candidate = datetime.combine(day, st, tzinfo=tz)
            if candidate <= local_now + timedelta(minutes=5):
                continue
            if any(abs((t - candidate).total_seconds()) < 1800 for t, _ in same_day):
                continue
            prev = [c for t, c in taken_local if t < candidate]
            if prev and prev[-1] == category and d == 0 and len(slot_times) > 1:
                # back-to-back same category: try a later slot/day first
                continue
            reason = f"Next free {cadence.get('per_day', 2)}/day slot ({st.strftime('%H:%M')} {timezone})"
            return candidate.astimezone(ZoneInfo("UTC")), reason
    fallback = now + timedelta(hours=1)
    return fallback, "No cadence slot free in 30 days; scheduled one hour from now"


async def taken_slots(db: AsyncSession, tenant_id, exclude_id=None) -> list[tuple[datetime, str]]:
    rows = (
        await db.execute(
            select(Publication.scheduled_at, Article.category)
            .join(Article, Article.id == Publication.article_id)
            .where(
                Publication.tenant_id == tenant_id,
                Publication.status.in_(("scheduled", "publishing", "published")),
                Publication.scheduled_at.is_not(None),
            )
        )
    ).all()
    return [(t, c) for t, c in rows if t is not None]


async def tick(db: AsyncSession) -> int:
    """Enqueue publish jobs for due publications across tenants. Dedupe makes repeated ticks harmless."""
    now = utcnow()
    due = (
        await db.execute(select(Publication).where(Publication.status == "scheduled", Publication.scheduled_at <= now))
    ).scalars().all()
    n = 0
    for pub in due:
        await enqueue(
            db,
            tenant_id=pub.tenant_id,
            type="publish",
            payload={"publication_id": str(pub.id), "dry_run": False},
            dedupe_key=f"pub:{pub.id}",
        )
        n += 1
    if n:
        await db.commit()
    return n


async def tenant_cadence(db: AsyncSession, tenant: Tenant) -> dict[str, Any]:
    from app.services.tenant_settings import effective

    return effective(tenant.settings).get("cadence", {})
