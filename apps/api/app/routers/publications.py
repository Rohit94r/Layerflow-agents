"""Publishing endpoints (plan §8.6): schedule, calendar, reschedule/cancel, publish now, dry run, artifact."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import orchestrator, publisher, scheduler
from app.agents.state import IllegalTransition
from app.core.audit import audit
from app.core.config import get_settings
from app.core.db import utcnow
from app.core.deps import ROLE_PUBLISH, Principal, current_principal, get_db, require
from app.core.errors import ApiError, bad_request, conflict
from app.models import Article, ArticleVersion, Publication, Tenant
from app.queue.jobs import PermanentError, enqueue
from app.routers.common import owned
from app.schemas import DryRunIn, PublicationIn, PublicationPatch
from app.serializers import job_out, publication_out
from app.services.fetcher import Fetcher
from app.services.integrations import integration_config
from app.services.tenant_settings import effective

router = APIRouter(prefix="/publications", tags=["publishing"])


def _target(tenant: Tenant, requested: str | None) -> str:
    return requested or integration_config(tenant)["default_target"] or "export"


@router.get("/next-slot")
async def next_slot(category: str = "brief", principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, principal.tenant_id)
    taken = await scheduler.taken_slots(db, tenant.id)
    when, reason = scheduler.next_slot(cadence=effective(tenant.settings)["cadence"], timezone=tenant.timezone, category=category, taken=taken)
    return {"scheduled_at": when.isoformat(), "reason": reason, "timezone": tenant.timezone, "default_target": _target(tenant, None)}


@router.post("", status_code=201)
async def schedule(body: PublicationIn, principal: Principal = Depends(require(ROLE_PUBLISH)), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, body.article_id, principal.tenant_id, "article")
    if article.state not in ("approved", "published"):
        raise conflict("not_approved", f"Only approved articles can be scheduled (state: {article.state})")
    tenant = await db.get(Tenant, principal.tenant_id)
    target = _target(tenant, body.target)
    version = await db.get(ArticleVersion, article.current_version_id) if article.current_version_id else None
    seo = ((version.payload if version else {}) or {}).get("seo") or {}
    if not seo.get("slug"):
        raise conflict("seo_missing", "Run SEO before scheduling")
    key = publisher.idempotency_key(tenant.slug, seo["slug"], article.content_hash or "", target)
    if body.scheduled_at:
        when = body.scheduled_at if body.scheduled_at.tzinfo else body.scheduled_at.replace(tzinfo=ZoneInfo(tenant.timezone))
        if when < utcnow() - timedelta(minutes=1):
            raise bad_request("in_past", "Scheduled time is in the past")
        reason = "Chosen by reviewer"
    else:
        when, reason = scheduler.next_slot(
            cadence=effective(tenant.settings)["cadence"], timezone=tenant.timezone, category=article.category,
            taken=await scheduler.taken_slots(db, tenant.id),
        )
    existing = (await db.execute(select(Publication).where(Publication.idempotency_key == key))).scalar_one_or_none()
    if existing is not None and existing.status in ("scheduled", "publishing", "published"):
        return {**publication_out(existing, article), "idempotent": True, "reason": "This exact version is already scheduled or published"}
    pub = existing or Publication(tenant_id=tenant.id, article_id=article.id, target=target, idempotency_key=key, created_by=principal.user.id)
    pub.version_id = article.current_version_id
    pub.status = "scheduled"
    pub.scheduled_at = when
    pub.last_error = None
    pub.content_hash = None
    if existing is None:
        db.add(pub)
    try:
        await orchestrator.transition(db, article, "scheduled", actor_type="user", actor_id=principal.user.id, reason=f"scheduled for {when.isoformat()} → {target}")
    except IllegalTransition as exc:
        raise conflict("illegal_transition", str(exc)) from exc
    await db.flush()
    audit(db, tenant_id=tenant.id, actor_type="user", actor_id=principal.user.id, action="publication.schedule", entity="publication", entity_id=pub.id,
          detail={"target": target, "scheduled_at": when.isoformat()})
    await db.commit()
    return {**publication_out(pub, article), "reason": reason}


@router.post("/dry-run")
async def dry_run(body: DryRunIn, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, body.article_id, principal.tenant_id, "article")
    tenant = await db.get(Tenant, principal.tenant_id)
    async with Fetcher() as fetcher:
        try:
            return await publisher.preview(db, tenant=tenant, article=article, target=_target(tenant, body.target), fetcher=fetcher)
        except PermanentError as exc:
            raise conflict("not_ready", str(exc)) from exc


@router.get("")
async def calendar(
    start: datetime | None = None, end: datetime | None = None, status: str | None = None,
    principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db),
):
    q = select(Publication, Article).join(Article, Article.id == Publication.article_id).where(Publication.tenant_id == principal.tenant_id)
    if start:
        q = q.where((Publication.scheduled_at >= start) | (Publication.published_at >= start))
    if end:
        q = q.where((Publication.scheduled_at <= end) | (Publication.published_at <= end))
    if status:
        q = q.where(Publication.status.in_(status.split(",")))
    rows = (await db.execute(q.order_by(Publication.scheduled_at.desc().nulls_last()).limit(500))).all()
    tenant = await db.get(Tenant, principal.tenant_id)
    tz = ZoneInfo(tenant.timezone)
    cadence = effective(tenant.settings)["cadence"]
    by_day: dict[str, list] = defaultdict(list)
    for pub, art in rows:
        if pub.status in ("scheduled", "publishing", "published") and (pub.scheduled_at or pub.published_at):
            day = (pub.scheduled_at or pub.published_at).astimezone(tz).date().isoformat()
            by_day[day].append((pub, art))
    conflicts = []
    for day, items in by_day.items():
        if len(items) > int(cadence.get("per_day", 2)):
            conflicts.append({"date": day, "kind": "per_day", "message": f"{len(items)} publications on {day}; cadence allows {cadence.get('per_day')}", "ids": [str(p.id) for p, _ in items]})
        cats: dict[str, list] = defaultdict(list)
        for p, a in items:
            cats[a.category].append(p)
        for cat, ps in cats.items():
            if len(ps) > int(cadence.get("max_per_category_per_day", 1)):
                conflicts.append({"date": day, "kind": "category", "message": f"{len(ps)} {cat} pieces on {day}", "ids": [str(p.id) for p in ps]})
    return {
        "items": [publication_out(p, a) for p, a in rows],
        "conflicts": conflicts,
        "timezone": tenant.timezone,
        "cadence": cadence,
    }


@router.patch("/{pub_id}")
async def update_publication(pub_id: str, body: PublicationPatch, principal: Principal = Depends(require(ROLE_PUBLISH)), db: AsyncSession = Depends(get_db)):
    pub = await owned(db, Publication, pub_id, principal.tenant_id, "publication")
    article = await db.get(Article, pub.article_id)
    if body.status == "cancelled":
        if pub.status not in ("scheduled", "failed"):
            raise conflict("illegal_transition", f"Cannot cancel a publication that is {pub.status}")
        pub.status = "cancelled"
        if article.state == "scheduled":
            await orchestrator.transition(db, article, "approved", actor_type="user", actor_id=principal.user.id, reason="publication cancelled")
        audit(db, tenant_id=pub.tenant_id, actor_type="user", actor_id=principal.user.id, action="publication.cancel", entity="publication", entity_id=pub.id)
    elif body.scheduled_at:
        if pub.status not in ("scheduled", "failed"):
            raise conflict("illegal_transition", f"Cannot reschedule a publication that is {pub.status}")
        tenant = await db.get(Tenant, principal.tenant_id)
        when = body.scheduled_at if body.scheduled_at.tzinfo else body.scheduled_at.replace(tzinfo=ZoneInfo(tenant.timezone))
        if when < utcnow() - timedelta(minutes=1):
            raise bad_request("in_past", "Scheduled time is in the past")
        pub.scheduled_at = when
        if pub.status == "failed":
            pub.status = "scheduled"
            pub.last_error = None
            if article.state == "approved":
                await orchestrator.transition(db, article, "scheduled", actor_type="user", actor_id=principal.user.id, reason="rescheduled after failure")
        audit(db, tenant_id=pub.tenant_id, actor_type="user", actor_id=principal.user.id, action="publication.reschedule", entity="publication", entity_id=pub.id, detail={"scheduled_at": when.isoformat()})
    else:
        raise bad_request("nothing_to_do", "Provide scheduled_at or status=cancelled")
    await db.commit()
    return publication_out(pub, article)


@router.post("/{pub_id}/publish-now")
async def publish_now(pub_id: str, principal: Principal = Depends(require(ROLE_PUBLISH)), db: AsyncSession = Depends(get_db)):
    pub = await owned(db, Publication, pub_id, principal.tenant_id, "publication")
    article = await db.get(Article, pub.article_id)
    if pub.status == "published":
        return {"publication": publication_out(pub, article), "job": None, "idempotent": True}
    if pub.status not in ("scheduled", "failed"):
        raise conflict("illegal_transition", f"Publication is {pub.status}")
    if article.state == "approved":
        await orchestrator.transition(db, article, "scheduled", actor_type="user", actor_id=principal.user.id, reason="publish now")
    if article.state not in ("scheduled", "published"):
        raise conflict("not_approved", f"Article is {article.state}")
    pub.status = "scheduled"
    pub.scheduled_at = utcnow()
    pub.last_error = None
    job = await enqueue(db, tenant_id=pub.tenant_id, type="publish", payload={"publication_id": str(pub.id)}, dedupe_key=f"pub:{pub.id}", created_by=principal.user.id)
    audit(db, tenant_id=pub.tenant_id, actor_type="user", actor_id=principal.user.id, action="publication.publish_now", entity="publication", entity_id=pub.id)
    await db.commit()
    return {"publication": publication_out(pub, article), "job": job_out(job)}


@router.post("/{pub_id}/rollback")
async def rollback(pub_id: str, principal: Principal = Depends(require(ROLE_PUBLISH)), db: AsyncSession = Depends(get_db)):
    pub = await owned(db, Publication, pub_id, principal.tenant_id, "publication")
    if pub.status != "published":
        raise conflict("illegal_transition", "Only published publications can be rolled back")
    if pub.target == "export":
        raise conflict("not_supported", "Export bundles are uploaded manually; remove the page on the server instead")
    async with Fetcher() as fetcher:
        try:
            await publisher.rollback(db, pub, fetcher)
        except PermanentError as exc:
            raise conflict("rollback_failed", str(exc)) from exc
    article = await db.get(Article, pub.article_id)
    still_live = (
        await db.execute(select(Publication.id).where(Publication.article_id == article.id, Publication.status == "published", Publication.id != pub.id).limit(1))
    ).scalar_one_or_none()
    if not still_live and article.state == "published":
        await orchestrator.transition(db, article, "approved", actor_type="user", actor_id=principal.user.id, reason="rolled back")
        article.published_url = None
    audit(db, tenant_id=pub.tenant_id, actor_type="user", actor_id=principal.user.id, action="publication.rollback", entity="publication", entity_id=pub.id)
    await db.commit()
    return publication_out(pub, article)


@router.get("/{pub_id}/artifact")
async def artifact(pub_id: str, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    pub = await owned(db, Publication, pub_id, principal.tenant_id, "publication")
    if not pub.artifact_path:
        raise ApiError(404, "not_found", "No export bundle for this publication")
    path = Path(pub.artifact_path).resolve()
    root = Path(get_settings().artifacts_dir).resolve()
    if root not in path.parents or not path.exists():
        raise ApiError(404, "not_found", "Bundle file is missing on disk")
    article = await db.get(Article, pub.article_id)
    return FileResponse(path, media_type="application/zip", filename=f"{article.slug or 'article'}-{path.stem}.zip")
