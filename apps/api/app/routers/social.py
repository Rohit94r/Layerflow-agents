"""LinkedIn distribution endpoints (plan §8.7). Publishing fails cleanly when no token exists; the copy/open
flow always works."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.distribution import valid_token
from app.core.audit import audit
from app.core.deps import ROLE_CONTENT, ROLE_PUBLISH, Principal, current_principal, get_db, require
from app.core.errors import ApiError, conflict
from app.models import Article, SocialPost, Tenant
from app.queue.jobs import enqueue
from app.routers.common import owned, parse_id
from app.schemas import SocialPatch
from app.serializers import job_out, social_out
from app.services import social_rules
from app.services.integrations import integration_config, linkedin_state

router = APIRouter(prefix="/social", tags=["social"])
GENERATABLE = frozenset({"qa", "in_review", "approved", "scheduled", "publishing", "published"})


async def connection(db: AsyncSession, tenant: Tenant) -> dict:
    cfg = integration_config(tenant)["linkedin"]
    token, author, reason = await valid_token(db, tenant)
    state = await linkedin_state(db, tenant.id)
    return {
        "configured": bool(cfg.get("client_id")),
        "connected": token is not None,
        "author_urn": author,
        "author_type": cfg.get("author_type"),
        "expires_at": state.get("expires_at"),
        "reason": None if token else reason,
    }


@router.get("")
async def list_posts(article_id: str | None = None, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    q = select(SocialPost, Article).join(Article, Article.id == SocialPost.article_id).where(SocialPost.tenant_id == principal.tenant_id)
    if article_id:
        q = q.where(SocialPost.article_id == parse_id(article_id, "article"))
    rows = (await db.execute(q.order_by(SocialPost.created_at.desc()).limit(200))).all()
    tenant = await db.get(Tenant, principal.tenant_id)
    candidates = (
        await db.execute(
            select(Article).where(Article.tenant_id == principal.tenant_id, Article.state.in_(("approved", "scheduled", "published", "in_review")))
            .order_by(Article.updated_at.desc()).limit(50)
        )
    ).unique().scalars().all()
    with_posts = {p.article_id for p, _ in rows}
    return {
        "items": [social_out(p, a) for p, a in rows],
        "connection": await connection(db, tenant),
        "articles_without_post": [
            {"id": str(a.id), "title": a.title, "category": a.category, "state": a.state} for a in candidates if a.id not in with_posts
        ],
    }


@router.post("/{article_id}/generate")
async def generate(article_id: str, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    if article.state not in GENERATABLE:
        raise conflict("not_ready", f"Generate the LinkedIn post once the article has passed QA (state: {article.state})")
    job = await enqueue(db, tenant_id=principal.tenant_id, type="social", payload={"article_id": str(article.id)}, dedupe_key=f"social:{article.id}", created_by=principal.user.id)
    await db.commit()
    return {"job": job_out(job)}


@router.patch("/{post_id}")
async def update_post(post_id: str, body: SocialPatch, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    post = await owned(db, SocialPost, post_id, principal.tenant_id, "social post")
    if post.status in ("published", "publishing"):
        raise conflict("illegal_transition", "Published posts cannot be edited")
    changes = body.model_dump(exclude_unset=True)
    if "hashtags" in changes and changes["hashtags"] is not None:
        changes["hashtags"] = social_rules.normalize_hashtags(changes["hashtags"])
    for k, v in changes.items():
        setattr(post, k, v)
    audit(db, tenant_id=post.tenant_id, actor_type="user", actor_id=principal.user.id, action="social.edit", entity="social_post", entity_id=post.id, detail={"fields": list(changes)})
    await db.commit()
    article = await db.get(Article, post.article_id)
    return social_out(post, article)


@router.post("/{post_id}/publish")
async def publish(post_id: str, principal: Principal = Depends(require(ROLE_PUBLISH)), db: AsyncSession = Depends(get_db)):
    post = await owned(db, SocialPost, post_id, principal.tenant_id, "social post")
    if post.status == "published":
        return {"post": social_out(post), "job": None, "idempotent": True}
    tenant = await db.get(Tenant, principal.tenant_id)
    token, _author, reason = await valid_token(db, tenant)
    if token is None:
        raise ApiError(409, "linkedin_not_connected", reason, {"fallback": "Copy the post and open LinkedIn"})
    issues = [i for i in social_rules.check_post(post.text, post.hashtags or []) if "characters" not in i]
    if issues:
        raise ApiError(422, "post_invalid", "Fix the post before publishing", issues)
    article = await db.get(Article, post.article_id)
    if article.state not in ("approved", "scheduled", "published"):
        raise conflict("not_approved", "Approve the article before posting it")
    post.status = "approved"
    job = await enqueue(db, tenant_id=post.tenant_id, type="distribute", payload={"social_post_id": str(post.id), "platform": "linkedin"}, dedupe_key=f"distribute:{post.id}", created_by=principal.user.id)
    audit(db, tenant_id=post.tenant_id, actor_type="user", actor_id=principal.user.id, action="social.publish", entity="social_post", entity_id=post.id)
    await db.commit()
    return {"post": social_out(post, article), "job": job_out(job)}


@router.post("/{post_id}/copied")
async def mark_copied(post_id: str, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    """Records that the post was copied for manual posting (audit trail for the fallback flow)."""
    post = await owned(db, SocialPost, post_id, principal.tenant_id, "social post")
    audit(db, tenant_id=post.tenant_id, actor_type="user", actor_id=principal.user.id, action="social.copied", entity="social_post", entity_id=post.id)
    await db.commit()
    return {"ok": True}
