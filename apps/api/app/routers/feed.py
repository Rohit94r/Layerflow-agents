"""Discovery endpoints (plan §8.3): feed, promote/ignore, sources CRUD + test."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import orchestrator
from app.core.audit import audit
from app.core.db import utcnow
from app.core.deps import ROLE_ADMIN, ROLE_CONTENT, Principal, current_principal, get_db, require
from app.core.errors import ApiError, conflict
from app.models import Article, FeedItem, Source, Topic
from app.queue.jobs import enqueue
from app.routers.common import owned, page_params, paginated, parse_id
from app.schemas import BulkPromoteIn, FeedRefreshIn, IgnoreIn, PromoteIn, SourceIn, SourcePatch
from app.serializers import article_summary, feed_item_out, job_out, source_out, topic_out
from app.services.dedupe import TfidfIndex
from app.services.feeds import FeedParseError, parse_ir_html, parse_source
from app.services.fetcher import FetchError, Fetcher

router = APIRouter(tags=["discovery"])


async def _cluster_sizes(db: AsyncSession, tenant_id, ids: list) -> dict:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(FeedItem.dedupe_cluster_id, func.count())
            .where(FeedItem.tenant_id == tenant_id, FeedItem.dedupe_cluster_id.in_(ids))
            .group_by(FeedItem.dedupe_cluster_id)
        )
    ).all()
    return {cid: n for cid, n in rows}


async def _topic_links(db: AsyncSession, item_ids: list) -> dict:
    if not item_ids:
        return {}
    rows = (
        await db.execute(
            select(Topic.feed_item_id, Topic.id, Article.id)
            .outerjoin(Article, Article.topic_id == Topic.id)
            .where(Topic.feed_item_id.in_(item_ids))
        )
    ).all()
    return {fid: (tid, aid) for fid, tid, aid in rows}


@router.get("/feed")
async def list_feed(
    category: str | None = None,
    region: str | None = None,
    source_id: str | None = None,
    q: str | None = None,
    min_score: float | None = Query(None, ge=0, le=1),
    since: datetime | None = None,
    status: str | None = Query(None, description="new|triaged|promoted|ignored|duplicate|all"),
    sort: str = Query("score", pattern="^(score|published|fetched)$"),
    include_duplicates: bool = False,
    page: int = 1,
    page_size: int = 50,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
):
    page, page_size, offset = page_params(page, page_size)
    query = select(FeedItem).where(FeedItem.tenant_id == principal.tenant_id)
    if category:
        query = query.where(FeedItem.suggested_category == category)
    if region:
        query = query.where(FeedItem.region == region)
    if source_id:
        query = query.where(FeedItem.source_id == parse_id(source_id, "source"))
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(FeedItem.title.ilike(like), FeedItem.summary.ilike(like), FeedItem.publisher.ilike(like)))
    if min_score is not None:
        query = query.where(FeedItem.score >= min_score)
    if since:
        query = query.where(FeedItem.fetched_at >= since)
    if status and status != "all":
        query = query.where(FeedItem.status == status)
    elif not status:
        query = query.where(FeedItem.status.in_(("new", "triaged", "promoted")))
    if not include_duplicates and status != "duplicate":
        query = query.where(FeedItem.is_cluster_head.is_(True))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    order = {
        "score": (FeedItem.score.desc(), FeedItem.published_at.desc()),
        "published": (FeedItem.published_at.desc().nulls_last(), FeedItem.score.desc()),
        "fetched": (FeedItem.fetched_at.desc(),),
    }[sort]
    rows = (await db.execute(query.order_by(*order).offset(offset).limit(page_size))).scalars().all()
    sizes = await _cluster_sizes(db, principal.tenant_id, [r.dedupe_cluster_id or r.id for r in rows])
    links = await _topic_links(db, [r.id for r in rows])
    items = []
    for r in rows:
        cid = r.dedupe_cluster_id or r.id
        tid, aid = links.get(r.id, (None, None))
        size = sizes.get(cid, 0) + (1 if r.dedupe_cluster_id is None else 0)
        items.append(feed_item_out(r, cluster_size=max(1, size), topic_id=tid, article_id=aid))
    last_fetch = (
        await db.execute(select(func.max(FeedItem.fetched_at)).where(FeedItem.tenant_id == principal.tenant_id))
    ).scalar_one()
    out = paginated(items, total, page, page_size)
    out["last_fetched_at"] = last_fetch.isoformat() if last_fetch else None
    out["stale"] = bool(last_fetch and utcnow() - last_fetch > timedelta(hours=6))
    return out


@router.post("/feed/refresh")
async def refresh_feed(body: FeedRefreshIn | None = None, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    source_id = body.source_id if body else None
    if source_id:
        await owned(db, Source, source_id, principal.tenant_id, "source")
    job = await enqueue(
        db,
        tenant_id=principal.tenant_id,
        type="discover",
        payload={"source_id": source_id} if source_id else {},
        dedupe_key=f"discover:{source_id or 'all'}",
        created_by=principal.user.id,
        priority=60,
    )
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="feed.refresh", entity="feed", detail={"source_id": source_id})
    await db.commit()
    return {"job": job_out(job)}


@router.get("/feed/{item_id}")
async def feed_detail(item_id: str, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    item = await owned(db, FeedItem, item_id, principal.tenant_id, "feed item")
    cid = item.dedupe_cluster_id or item.id
    cluster = (
        await db.execute(
            select(FeedItem).where(FeedItem.tenant_id == principal.tenant_id, or_(FeedItem.dedupe_cluster_id == cid, FeedItem.id == cid), FeedItem.id != item.id)
        )
    ).scalars().all()
    recent = (
        await db.execute(
            select(FeedItem)
            .where(FeedItem.tenant_id == principal.tenant_id, FeedItem.fetched_at >= utcnow() - timedelta(days=14), FeedItem.id != item.id, FeedItem.is_cluster_head.is_(True))
            .limit(800)
        )
    ).scalars().all()
    similar = []
    if recent:
        idx = TfidfIndex([f"{r.title} {r.summary or ''}" for r in recent] + [f"{item.title} {item.summary or ''}"])
        me = idx.vectors[-1]
        scored = sorted(((TfidfIndex.cosine(me, idx.vectors[i]), r) for i, r in enumerate(recent)), key=lambda x: -x[0])
        similar = [(round(s, 3), r) for s, r in scored[:6] if s >= 0.15 and r.id not in {c.id for c in cluster}]
    links = await _topic_links(db, [item.id])
    tid, aid = links.get(item.id, (None, None))
    topic = await db.get(Topic, tid) if tid else None
    return {
        "item": feed_item_out(item, cluster_size=len(cluster) + 1, topic_id=tid, article_id=aid),
        "cluster": [feed_item_out(c) for c in cluster],
        "similar": [{**feed_item_out(r), "similarity": s} for s, r in similar],
        "topic": topic_out(topic) if topic else None,
        "article_id": str(aid) if aid else None,
    }


async def _promote(db: AsyncSession, principal: Principal, item: FeedItem, *, category: str | None, angle: str | None, auto: bool) -> dict[str, Any]:
    links = await _topic_links(db, [item.id])
    if item.id in links and links[item.id][1]:
        raise conflict("already_promoted", "This story is already in the studio", {"article_id": str(links[item.id][1])})
    cat = category or item.suggested_category or "thinking"
    topic = Topic(
        tenant_id=principal.tenant_id,
        feed_item_id=item.id,
        category=cat,
        title=item.title,
        angle=angle or item.why_it_matters,
        region=item.region,
        links=[item.url],
        status="promoted",
        created_by=principal.user.id,
    )
    db.add(topic)
    await db.flush()
    article = Article(tenant_id=principal.tenant_id, topic_id=topic.id, category=cat, state="queued", title=item.title[:300], created_by=principal.user.id)
    db.add(article)
    await db.flush()
    item.status = "promoted"
    job = await orchestrator.start_stage(db, article, "auto" if auto else "research", auto=auto, user_id=principal.user.id)
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="feed.promote", entity="article",
          entity_id=article.id, detail={"feed_item_id": str(item.id), "category": cat})
    await db.refresh(article, ["topic"])
    return {"topic": topic_out(topic), "article": article_summary(article, job), "job": job_out(job)}


@router.post("/feed/{item_id}/promote")
async def promote(item_id: str, body: PromoteIn | None = None, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    body = body or PromoteIn()
    item = await owned(db, FeedItem, item_id, principal.tenant_id, "feed item")
    out = await _promote(db, principal, item, category=body.category, angle=body.angle, auto=body.auto)
    await db.commit()
    return out


@router.post("/feed/promote-bulk")
async def promote_bulk(body: BulkPromoteIn, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    results = []
    for raw in body.ids:
        try:
            item = await owned(db, FeedItem, raw, principal.tenant_id, "feed item")
            out = await _promote(db, principal, item, category=None, angle=None, auto=body.auto)
            results.append({"id": raw, "ok": True, "article_id": out["article"]["id"]})
        except ApiError as exc:
            results.append({"id": raw, "ok": False, "error": exc.message})
    await db.commit()
    return {"results": results, "promoted": sum(1 for r in results if r["ok"])}


@router.post("/feed/{item_id}/ignore")
async def ignore(item_id: str, body: IgnoreIn | None = None, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    item = await owned(db, FeedItem, item_id, principal.tenant_id, "feed item")
    if item.status == "promoted":
        raise conflict("already_promoted", "Promoted stories cannot be ignored; archive the article instead")
    item.status = "ignored"
    item.ignored_reason = (body.reason if body else "Not relevant")[:500]
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="feed.ignore", entity="feed_item", entity_id=item.id, detail={"reason": item.ignored_reason})
    await db.commit()
    return {"item": feed_item_out(item)}


@router.post("/feed/{item_id}/restore")
async def restore(item_id: str, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    item = await owned(db, FeedItem, item_id, principal.tenant_id, "feed item")
    if item.status == "ignored":
        item.status = "new"
        item.ignored_reason = None
        await db.commit()
    return {"item": feed_item_out(item)}


# ---------------- sources ----------------
@router.get("/sources")
async def list_sources(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Source).where(Source.tenant_id == principal.tenant_id).order_by(Source.active.desc(), Source.name))).scalars().all()
    counts = dict(
        (
            await db.execute(
                select(FeedItem.source_id, func.count())
                .where(FeedItem.tenant_id == principal.tenant_id, FeedItem.fetched_at >= utcnow() - timedelta(days=7))
                .group_by(FeedItem.source_id)
            )
        ).all()
    )
    return {"items": [source_out(s, counts.get(s.id, 0)) for s in rows]}


@router.post("/sources", status_code=201)
async def create_source(body: SourceIn, principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    url = str(body.url)
    exists = (await db.execute(select(Source.id).where(Source.tenant_id == principal.tenant_id, Source.url == url))).scalar_one_or_none()
    if exists:
        raise conflict("duplicate_source", "A source with this URL already exists")
    src = Source(tenant_id=principal.tenant_id, kind=body.kind, name=body.name, url=url, weight=body.weight, region=body.region, active=body.active)
    db.add(src)
    await db.flush()
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="source.create", entity="source", entity_id=src.id, detail={"url": url})
    await db.commit()
    return source_out(src, 0)


@router.patch("/sources/{source_id}")
async def update_source(source_id: str, body: SourcePatch, principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    src = await owned(db, Source, source_id, principal.tenant_id, "source")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(src, k, str(v) if k == "url" and v is not None else v)
    if changes.get("active"):
        src.consecutive_failures = 0
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="source.update", entity="source", entity_id=src.id, detail={k: str(v) for k, v in changes.items()})
    await db.commit()
    return source_out(src)


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str, principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    src = await owned(db, Source, source_id, principal.tenant_id, "source")
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="source.delete", entity="source", entity_id=src.id, detail={"url": src.url})
    await db.delete(src)
    await db.commit()
    return {"ok": True}


@router.post("/sources/{source_id}/test")
async def test_source(source_id: str, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    src = await owned(db, Source, source_id, principal.tenant_id, "source")
    started = time.perf_counter()
    async with Fetcher() as fetcher:
        try:
            res = await fetcher.get(src.url, respect_robots=False, use_cache=False)
            items = parse_ir_html(res.text, src.url) if (src.kind == "ir" and res.content_type == "text/html") else parse_source(src.kind, res.text)
            error = None
        except (FetchError, FeedParseError) as exc:
            items, error = [], str(exc)
    latency = int((time.perf_counter() - started) * 1000)
    src.last_latency_ms = latency
    src.last_error = error
    if error is None:
        src.last_item_count = len(items)
    await db.commit()
    return {
        "ok": error is None,
        "item_count": len(items),
        "latency_ms": latency,
        "error": error,
        "sample": [{"title": i.title, "url": i.url, "published_at": i.published_at.isoformat() if i.published_at else None} for i in items[:5]],
    }
