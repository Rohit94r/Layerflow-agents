"""Job visibility and retry (failed jobs are never silently lost) + global search for ⌘K."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import orchestrator
from app.agents.state import STAGE_ORDER, STAGE_STATE, IllegalTransition
from app.core.audit import audit
from app.core.deps import ROLE_CONTENT, Principal, current_principal, get_db, require
from app.core.errors import conflict
from app.models import Article, FeedItem, Job, JobEvent, Publication, SocialPost, Source
from app.queue import jobs as q
from app.routers.common import owned, page_params, paginated, parse_id
from app.serializers import article_summary, feed_item_out, job_event_out, job_out, source_out

router = APIRouter(tags=["jobs"])


@router.get("/jobs")
async def list_jobs(
    status: str | None = Query(None, description="comma-separated"),
    type: str | None = None,
    article_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
):
    page, page_size, offset = page_params(page, page_size)
    query = select(Job).where(Job.tenant_id == principal.tenant_id)
    if status:
        query = query.where(Job.status.in_(status.split(",")))
    if type:
        query = query.where(Job.type == type)
    if article_id:
        query = query.where(Job.article_id == parse_id(article_id, "article"))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (await db.execute(query.order_by(Job.created_at.desc()).offset(offset).limit(page_size))).scalars().all()
    titles = {}
    ids = [j.article_id for j in rows if j.article_id]
    if ids:
        titles = {a: t for a, t in (await db.execute(select(Article.id, Article.title).where(Article.id.in_(ids)))).all()}
    items = [{**job_out(j), "article_title": titles.get(j.article_id)} for j in rows]
    return paginated(items, total, page, page_size)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    job = await owned(db, Job, job_id, principal.tenant_id, "job")
    events = (await db.execute(select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.id).limit(500))).scalars().all()
    return {"job": job_out(job), "events": [job_event_out(e) for e in events]}


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    job = await owned(db, Job, job_id, principal.tenant_id, "job")
    if job.status not in ("failed", "dead"):
        raise conflict("not_failed", f"Only failed jobs can be retried (status: {job.status})")
    if job.type in STAGE_ORDER and job.article_id:
        article = await db.get(Article, job.article_id)
        if article is not None:
            if await orchestrator.active_job(db, article.id):
                raise conflict("busy", "Another job is already running for this article")
            try:
                await orchestrator.transition(db, article, STAGE_STATE[job.type], actor_type="user", actor_id=principal.user.id, reason=f"retry {job.type}")
            except IllegalTransition as exc:
                raise conflict("illegal_transition", f"Article moved on ({article.state}); start the stage from the Studio instead") from exc
    if job.type == "publish":
        pub = await db.get(Publication, uuid.UUID(job.payload["publication_id"]))
        if pub is not None:
            pub.status = "scheduled"
            pub.last_error = None
            article = await db.get(Article, pub.article_id)
            if article is not None and article.state == "approved":
                await orchestrator.transition(db, article, "scheduled", actor_type="user", actor_id=principal.user.id, reason="retry publish")
    if job.type == "distribute":
        post = await db.get(SocialPost, uuid.UUID(job.payload["social_post_id"]))
        if post is not None and post.status == "failed":
            post.status = "approved"
    await q.retry(db, job)
    audit(db, tenant_id=job.tenant_id, actor_type="user", actor_id=principal.user.id, action="job.retry", entity="job", entity_id=job.id, detail={"type": job.type})
    await db.commit()
    return {"job": job_out(job)}


@router.get("/search")
async def search(q_: str = Query(..., alias="q", min_length=2, max_length=100), principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    like = f"%{q_.strip()}%"
    arts = (
        await db.execute(
            select(Article).where(Article.tenant_id == principal.tenant_id, or_(Article.title.ilike(like), Article.slug.ilike(like))).order_by(Article.updated_at.desc()).limit(8)
        )
    ).unique().scalars().all()
    feed = (
        await db.execute(
            select(FeedItem)
            .where(FeedItem.tenant_id == principal.tenant_id, FeedItem.is_cluster_head.is_(True), or_(FeedItem.title.ilike(like), FeedItem.publisher.ilike(like)))
            .order_by(FeedItem.fetched_at.desc())
            .limit(8)
        )
    ).scalars().all()
    sources = (await db.execute(select(Source).where(Source.tenant_id == principal.tenant_id, Source.name.ilike(like)).limit(5))).scalars().all()
    return {"articles": [article_summary(a) for a in arts], "feed": [feed_item_out(f) for f in feed], "sources": [source_out(s) for s in sources]}
