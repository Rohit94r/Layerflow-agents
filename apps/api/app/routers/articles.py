"""Topics, articles, versions, review actions and the live event stream (plan §8.4)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import orchestrator
from app.agents.research import latest_pack
from app.agents.state import IllegalTransition, runnable_stages
from app.core.audit import audit
from app.core.db import session_factory, utcnow
from app.core.deps import ROLE_ADMIN, ROLE_CONTENT, ROLE_REVIEW, Principal, current_principal, get_db, require
from app.core.errors import ApiError, conflict
from app.models import Article, ArticleVersion, Job, JobEvent, Publication, ReviewAction, SocialPost, Tenant, Topic, User
from app.routers.common import owned, page_params, paginated, parse_id
from app.schemas import ArticlePatch, ForceReviewIn, RejectIn, RequestRevisionIn, ReviewIn, ReviseIn, RunStageIn, TopicIn
from app.serializers import (
    article_summary,
    job_event_out,
    job_out,
    publication_out,
    research_out,
    review_action_out,
    social_out,
    topic_out,
    version_out,
)
from app.services.article_doc import compute_stats, normalise_sections
from app.services.formatter import format_report
from app.services.playbooks import public_playbooks
from app.services.prompts import banned_list
from app.services.render import render_article
from app.services.tenant_settings import effective
from app.services.versions import add_version, current_payload, list_versions

router = APIRouter(tags=["articles"])
EDITABLE_STATES = frozenset({"drafting", "editing", "seo", "qa", "in_review", "approved", "published", "failed", "needs_sources"})


def _illegal(exc: IllegalTransition) -> ApiError:
    return conflict("illegal_transition", str(exc), {"from": exc.current, "to": exc.target})


async def _active_jobs(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, Job]:
    if not ids:
        return {}
    rows = (
        await db.execute(select(Job).where(Job.article_id.in_(ids), Job.status.in_(("queued", "running"))).order_by(Job.created_at))
    ).scalars().all()
    return {j.article_id: j for j in rows}


async def article_detail(db: AsyncSession, article: Article, principal: Principal) -> dict[str, Any]:
    version = await db.get(ArticleVersion, article.current_version_id) if article.current_version_id else None
    pack = await latest_pack(db, article.id)
    jobs = (await db.execute(select(Job).where(Job.article_id == article.id).order_by(Job.created_at.desc()).limit(40))).scalars().all()
    active = next((j for j in jobs if j.status in ("queued", "running")), None)
    pubs = (await db.execute(select(Publication).where(Publication.article_id == article.id).order_by(Publication.created_at.desc()))).scalars().all()
    posts = (await db.execute(select(SocialPost).where(SocialPost.article_id == article.id).order_by(SocialPost.created_at.desc()))).scalars().all()
    reviews = (
        await db.execute(
            select(ReviewAction, User).outerjoin(User, User.id == ReviewAction.user_id).where(ReviewAction.article_id == article.id).order_by(ReviewAction.created_at.desc())
        )
    ).all()
    payload = version.payload if version else {}
    busy = active is not None
    stages = runnable_stages(article.state, busy=busy)
    is_review = principal.can(ROLE_REVIEW)
    is_content = principal.can(ROLE_CONTENT)
    has_seo = bool((payload or {}).get("seo"))
    return {
        **article_summary(article, active),
        "current_version": version_out(version) if version else None,
        "research_pack": research_out(pack) if pack else None,
        "seo": (payload or {}).get("seo"),
        "qa": (payload or {}).get("qa"),
        "editor": (payload or {}).get("editor"),
        "stats": (payload or {}).get("stats"),
        "playbook": next(p for p in public_playbooks() if p["key"] == article.category),
        "jobs": [job_out(j) for j in jobs],
        "publications": [publication_out(p, article) for p in pubs],
        "social_posts": [social_out(p, article) for p in posts],
        "review_actions": [review_action_out(r, u) for r, u in reviews],
        "allowed_actions": {
            "run_stages": stages if is_content else [],
            "can_run_auto": is_content and not busy and "research" in stages,
            "can_edit": is_content and article.state in EDITABLE_STATES and not busy,
            "can_approve": is_review and article.state == "in_review" and not busy,
            "can_reject": is_review and article.state in ("in_review", "approved", "failed", "needs_sources", "queued") and not busy,
            "can_request_revision": is_review and article.state in ("in_review", "approved") and not busy,
            "can_force_review": principal.can(ROLE_ADMIN) and article.state in ("failed", "qa") and bool(payload.get("article")) and has_seo and not busy,
            "can_schedule": is_review and article.state in ("approved", "published") and not busy,
            "can_restore": is_content and not busy and article.state not in ("scheduled", "publishing"),
            "busy_reason": f"{active.type} job is {active.status}" if active else None,
        },
    }


@router.get("/playbooks")
async def playbooks(_: Principal = Depends(current_principal)):
    return {"items": public_playbooks()}


@router.post("/topics", status_code=201)
async def create_topic(body: TopicIn, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    topic = Topic(
        tenant_id=principal.tenant_id,
        category=body.category,
        title=body.title,
        angle=body.angle,
        region=body.region,
        notes=body.notes,
        links=[str(u) for u in body.links],
        status="manual",
        created_by=principal.user.id,
    )
    db.add(topic)
    await db.flush()
    article = Article(tenant_id=principal.tenant_id, topic_id=topic.id, category=body.category, state="queued", title=body.title[:300], created_by=principal.user.id)
    db.add(article)
    await db.flush()
    job = await orchestrator.start_stage(db, article, "auto" if body.auto else "research", auto=body.auto, user_id=principal.user.id)
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="topic.create", entity="article", entity_id=article.id, detail={"category": body.category})
    await db.commit()
    await db.refresh(article, ["topic"])
    return {"topic": topic_out(topic), "article": article_summary(article, job), "job": job_out(job)}


@router.get("/articles")
async def list_articles(
    state: str | None = Query(None, description="comma-separated states"),
    category: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
):
    page, page_size, offset = page_params(page, page_size)
    query = select(Article).where(Article.tenant_id == principal.tenant_id)
    if state:
        query = query.where(Article.state.in_([s.strip() for s in state.split(",") if s.strip()]))
    if category:
        query = query.where(Article.category == category)
    if q:
        query = query.where(or_(Article.title.ilike(f"%{q}%"), Article.slug.ilike(f"%{q}%")))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (await db.execute(query.order_by(Article.updated_at.desc()).offset(offset).limit(page_size))).unique().scalars().all()
    active = await _active_jobs(db, [a.id for a in rows])
    items = [article_summary(a, active.get(a.id)) for a in rows]
    # Review queue needs QA scores without N detail calls.
    ids = [a.current_version_id for a in rows if a.current_version_id]
    if ids:
        qa = {v.id: (v.payload or {}).get("qa") for v in (await db.execute(select(ArticleVersion).where(ArticleVersion.id.in_(ids)))).scalars()}
        for item, a in zip(items, rows, strict=False):
            rep = qa.get(a.current_version_id) or {}
            item["qa_verdict"] = rep.get("verdict")
            item["qa_overall"] = rep.get("overall")
    return paginated(items, total, page, page_size)


@router.get("/articles/{article_id}")
async def get_article(article_id: str, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    return await article_detail(db, article, principal)


@router.post("/articles/{article_id}/run")
async def run_stage(article_id: str, body: RunStageIn, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    try:
        job = await orchestrator.start_stage(db, article, body.stage, auto=body.stage == "auto", user_id=principal.user.id)
    except IllegalTransition as exc:
        raise _illegal(exc) from exc
    await db.commit()
    return {"job": job_out(job)}


@router.post("/articles/{article_id}/revise")
async def revise(article_id: str, body: ReviseIn, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    if not article.current_version_id:
        raise conflict("no_content", "Nothing to revise yet")
    try:
        job = await orchestrator.start_stage(db, article, body.stage, auto=False, user_id=principal.user.id, instruction=body.instruction)
    except IllegalTransition as exc:
        raise _illegal(exc) from exc
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="article.revise", entity="article", entity_id=article.id, detail={"stage": body.stage, "instruction": body.instruction[:300]})
    await db.commit()
    return {"job": job_out(job)}


@router.get("/articles/{article_id}/versions")
async def versions(article_id: str, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    rows = await list_versions(db, article.id)
    return {"items": [version_out(v) for v in rows], "current_version_id": str(article.current_version_id) if article.current_version_id else None}


@router.post("/articles/{article_id}/versions/{version_id}/restore")
async def restore_version(article_id: str, version_id: str, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    if await orchestrator.active_job(db, article.id):
        raise conflict("busy", "Wait for the running job to finish before restoring")
    if article.state in ("scheduled", "publishing"):
        raise conflict("illegal_transition", "Cancel the scheduled publication before restoring a version")
    v = await db.get(ArticleVersion, parse_id(version_id, "version"))
    if v is None or v.article_id != article.id:
        raise ApiError(404, "not_found", "Version not found")
    payload = dict(v.payload)
    payload["qa"] = None if v.stage != "qa" else payload.get("qa")
    await add_version(db, article, stage="restored", payload=payload, created_by=principal.user.id, note=f"Restored version from {v.created_at:%d %b %H:%M} ({v.stage})")
    if article.state in ("in_review", "approved", "published"):
        await orchestrator.transition(db, article, "in_review" if v.stage == "qa" and (payload.get("qa") or {}).get("verdict") == "pass" else "editing",
                                      actor_type="user", actor_id=principal.user.id, reason="version restored")
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="article.restore", entity="article", entity_id=article.id, detail={"version_id": version_id})
    await db.commit()
    return await article_detail(db, article, principal)


@router.patch("/articles/{article_id}")
async def patch_article(article_id: str, body: ArticlePatch, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    if await orchestrator.active_job(db, article.id):
        raise conflict("busy", "An agent is working on this article; wait for it to finish")
    if article.state not in EDITABLE_STATES:
        raise conflict("illegal_transition", f"Articles in '{article.state}' cannot be edited")
    payload = await current_payload(db, article)
    art = dict(payload.get("article") or {})
    if not art:
        raise conflict("no_content", "Nothing to edit yet; run Write first")
    changes = body.model_dump(exclude_unset=True, exclude={"note"})
    if "sections" in changes and changes["sections"] is not None:
        art["sections"] = [s for s in changes.pop("sections")]
    for k, v in changes.items():
        if v is not None:
            art[k] = v
    art = normalise_sections(art)
    async with session_factory()() as tmp:
        banned = await banned_list(tmp, principal.tenant_id)
    stats = compute_stats(art, banned_phrases=banned)
    editor = dict(payload.get("editor") or {})
    editor["format_report"] = format_report(art)
    new_payload = {**payload, "article": art, "stats": stats, "editor": editor, "qa": None}
    await add_version(db, article, stage="manual", payload=new_payload, created_by=principal.user.id, note=body.note or "Manual edit")
    # A human edit invalidates QA and approval: the article goes back through QA before review.
    if article.state in ("in_review", "approved", "published"):
        await orchestrator.transition(db, article, "qa" if article.state != "published" else "editing", actor_type="user", actor_id=principal.user.id, reason="manual edit")
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="article.edit", entity="article", entity_id=article.id, detail={"fields": list(body.model_dump(exclude_unset=True))})
    await db.commit()
    return await article_detail(db, article, principal)


async def _review(db: AsyncSession, article: Article, principal: Principal, action: str, reason: str | None) -> None:
    db.add(ReviewAction(article_id=article.id, user_id=principal.user.id, action=action, reason=reason))
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action=f"review.{action}", entity="article", entity_id=article.id, detail={"reason": reason})


@router.post("/articles/{article_id}/approve")
async def approve(article_id: str, body: ReviewIn | None = None, principal: Principal = Depends(require(ROLE_REVIEW)), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    if article.state != "in_review":
        raise conflict("illegal_transition", f"Only articles in review can be approved (state: {article.state})")
    payload = await current_payload(db, article)
    if not (payload.get("seo") or {}).get("slug"):
        raise conflict("seo_missing", "Run SEO before approving (no slug)")
    await orchestrator.transition(db, article, "approved", actor_type="user", actor_id=principal.user.id, reason="approved")
    await _review(db, article, principal, "approve", body.note if body else None)
    await db.commit()
    return await article_detail(db, article, principal)


@router.post("/articles/{article_id}/reject")
async def reject(article_id: str, body: RejectIn, principal: Principal = Depends(require(ROLE_REVIEW)), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    if await orchestrator.active_job(db, article.id):
        raise conflict("busy", "An agent is working on this article")
    try:
        await orchestrator.transition(db, article, "archived", actor_type="user", actor_id=principal.user.id, reason=body.reason)
    except IllegalTransition as exc:
        raise _illegal(exc) from exc
    await _review(db, article, principal, "reject", body.reason)
    await db.commit()
    return await article_detail(db, article, principal)


@router.post("/articles/{article_id}/request-revision")
async def request_revision(article_id: str, body: RequestRevisionIn, principal: Principal = Depends(require(ROLE_REVIEW)), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    if article.state not in ("in_review", "approved"):
        raise conflict("illegal_transition", f"Revisions can be requested for articles in review (state: {article.state})")
    await _review(db, article, principal, "request_revision", body.reason)
    try:
        # Revision runs the stage, then continues through the remaining stages back to review.
        job = await orchestrator.start_stage(db, article, body.stage, auto=True, user_id=principal.user.id, instruction=body.reason)
    except IllegalTransition as exc:
        raise _illegal(exc) from exc
    await db.commit()
    return {**(await article_detail(db, article, principal)), "job": job_out(job)}


@router.post("/articles/{article_id}/force-review")
async def force_review(article_id: str, body: ForceReviewIn, principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    """Owner override: send an article with failing QA gates to human review. Logged with the reason."""
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    if article.state not in ("failed", "qa"):
        raise conflict("illegal_transition", f"Override applies to failed or QA-held articles (state: {article.state})")
    payload = await current_payload(db, article)
    if not payload.get("article") or not (payload.get("seo") or {}).get("slug"):
        raise conflict("incomplete", "Article needs a draft and SEO before review")
    try:
        await orchestrator.transition(db, article, "in_review", actor_type="user", actor_id=principal.user.id, reason=f"QA override: {body.reason}")
    except IllegalTransition as exc:
        raise _illegal(exc) from exc
    await _review(db, article, principal, "force_review", body.reason)
    await db.commit()
    return await article_detail(db, article, principal)


@router.post("/articles/{article_id}/archive")
async def archive(article_id: str, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    if await orchestrator.active_job(db, article.id):
        raise conflict("busy", "An agent is working on this article")
    try:
        await orchestrator.transition(db, article, "archived", actor_type="user", actor_id=principal.user.id, reason="archived from studio")
    except IllegalTransition as exc:
        raise _illegal(exc) from exc
    await db.commit()
    return await article_detail(db, article, principal)


@router.get("/articles/{article_id}/preview", response_class=HTMLResponse)
async def preview(article_id: str, version_id: str | None = None, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    vid = parse_id(version_id, "version") if version_id else article.current_version_id
    v = await db.get(ArticleVersion, vid) if vid else None
    if v is None or v.article_id != article.id or not (v.payload or {}).get("article"):
        return HTMLResponse("<p style='font-family:sans-serif;color:#666;padding:24px'>No draft yet.</p>")
    tenant = await db.get(Tenant, principal.tenant_id)
    eff = effective(tenant.settings)
    payload = dict(v.payload)
    if not payload.get("seo"):
        art = payload["article"]
        payload["seo"] = {"title_tag": art.get("title"), "meta_description": art.get("dek"), "slug": "draft", "og": {}, "twitter": {}, "json_ld": []}
    from app.agents.publisher import finalize_payload

    final = finalize_payload(payload, tenant, article.updated_at)
    html = render_article(final, brand=eff.get("brand", {}), published_at=article.updated_at, timezone=tenant.timezone, spelling=eff.get("spelling", "en-US"))
    return HTMLResponse(html, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline' https:; img-src https: data:; font-src https:; frame-ancestors 'self'", "X-Frame-Options": "SAMEORIGIN"})


@router.get("/articles/{article_id}/events")
async def events(article_id: str, request: Request, after: int = 0, principal: Principal = Depends(current_principal)):
    """SSE: `state` (article state/last_error), `job` (job changes) and `log` (job_events) until the client leaves."""
    aid = parse_id(article_id, "article")
    async with session_factory()() as db:
        article = await db.get(Article, aid)
        if article is None or article.tenant_id != principal.tenant_id:
            raise ApiError(404, "not_found", "Article not found")

    async def stream():
        last_event = after
        last_state = None
        last_jobs: dict[str, str] = {}
        deadline = asyncio.get_running_loop().time() + 1800
        yield "retry: 3000\n\n"
        while asyncio.get_running_loop().time() < deadline:
            if await request.is_disconnected():
                break
            async with session_factory()() as db:
                art = await db.get(Article, aid)
                if art is None:
                    break
                state = (art.state, art.last_error, str(art.current_version_id))
                if state != last_state:
                    last_state = state
                    yield f"event: state\ndata: {json.dumps({'state': art.state, 'last_error': art.last_error, 'current_version_id': state[2], 'updated_at': art.updated_at.isoformat()})}\n\n"
                rows = (await db.execute(select(JobEvent).where(JobEvent.article_id == aid, JobEvent.id > last_event).order_by(JobEvent.id).limit(200))).scalars().all()
                for e in rows:
                    last_event = e.id
                    yield f"id: {e.id}\nevent: log\ndata: {json.dumps(job_event_out(e))}\n\n"
                jobs = (await db.execute(select(Job).where(Job.article_id == aid).order_by(Job.created_at.desc()).limit(10))).scalars().all()
                for j in jobs:
                    sig = f"{j.status}:{j.attempts}:{j.finished_at}"
                    if last_jobs.get(str(j.id)) != sig:
                        last_jobs[str(j.id)] = sig
                        yield f"event: job\ndata: {json.dumps(job_out(j), default=str)}\n\n"
            yield ": ping\n\n"
            await asyncio.sleep(1.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/articles/{article_id}/logs")
async def logs(article_id: str, after: int = 0, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    """Polling fallback for the event stream."""
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    rows = (await db.execute(select(JobEvent).where(JobEvent.article_id == article.id, JobEvent.id > after).order_by(JobEvent.id).limit(500))).scalars().all()
    return {"items": [job_event_out(e) for e in rows]}

