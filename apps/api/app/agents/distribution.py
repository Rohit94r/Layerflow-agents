"""A9 Distribution — native-feeling LinkedIn post from the final article; publishes only through the official
API with a legitimate token. Without one the post is `draft_ready` (copy + open LinkedIn), which always works."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from app.adapters import linkedin
from app.agents.base import AgentContext, structured
from app.core.audit import audit
from app.core.db import session_factory, utcnow
from app.models import Article, ArticleVersion, SocialPost, Tenant
from app.queue.jobs import PermanentError, RetryableError
from app.services import social_rules
from app.services.integrations import get_secret, integration_config, linkedin_state, set_linkedin_state, set_secret
from app.services.prompts import compose_system, versions_tag
from app.services.text import numbers_in


class LinkedInOut(BaseModel):
    hook: str = Field(min_length=20, max_length=210, description="first 1–2 lines; all that shows before 'see more'")
    body: str = Field(min_length=200, max_length=1000)
    leaders_line: str = Field(min_length=20, max_length=240, description="what this means for leaders")
    cta: str = Field(default="", max_length=140)
    hashtags: list[str] = Field(default_factory=list, max_length=3)


def _article_link(article: Article, payload: dict[str, Any]) -> str:
    if article.published_url and not article.published_url.startswith(("http://localhost", "http://127.")):
        return article.published_url
    return (payload.get("seo") or {}).get("canonical_url") or article.published_url or ""


async def run_social_generate(ctx: AgentContext, article_id: uuid.UUID) -> dict[str, Any]:
    async with session_factory()() as db:
        article = await db.get(Article, article_id)
        if article is None or article.current_version_id is None:
            raise PermanentError("Article has no content")
        version = await db.get(ArticleVersion, article.current_version_id)
        payload = version.payload
        system, used = await compose_system(db, ctx.tenant.id, agent="linkedin", category=article.category)
    art = payload.get("article") or {}
    seo = payload.get("seo") or {}
    link = _article_link(article, payload)
    social_cfg = ctx.tenant.settings.get("social", {})
    emoji = bool(social_cfg.get("emoji", False))
    opening = next((p for s in art.get("sections") or [] for p in s.get("paragraphs") or []), "")
    allowed = numbers_in(" ".join([art.get("title", ""), art.get("dek", ""), art.get("takeaway", "")] + [p for s in art.get("sections") or [] for p in s.get("paragraphs") or []]))

    def validate(out: LinkedInOut) -> list[str]:
        tags = social_rules.normalize_hashtags(out.hashtags)
        text = social_rules.fit_length(out.hook, out.body, out.leaders_line, out.cta, link, tags, emoji=emoji)
        problems = [i for i in social_rules.check_post(text, tags, opening_paragraph=opening) if "No link" not in i or link]
        if "characters" in " ".join(problems) and len(text) < social_rules.MIN_CHARS:
            problems = [p for p in problems if "characters" not in p] + [f"post is {len(text)} characters; write more body (target 800–1,200)"]
        bad = numbers_in(text) - allowed
        if bad:
            problems.append(f"numbers {', '.join(sorted(bad))} are not in the article")
        return problems

    prompt = (
        f"Article title: {art.get('title')}\nDek: {art.get('dek')}\nCategory: {art.get('category')}\n"
        f"Takeaway: {art.get('takeaway')}\n"
        "Key paragraphs:\n" + "\n".join(f"- {p}" for s in (art.get("sections") or [])[:4] for p in (s.get("paragraphs") or [])[:1])
        + f"\nPrimary keyword: {seo.get('primary_keyword', '')}\n\n"
        "Write a LinkedIn post for The Executive Narrative's page: a hook in the first two lines, a body with one concrete number "
        "or tension from the article, a line on what this means for leaders, a short call to read the piece, up to 3 hashtags. "
        f"Total 700–1,300 characters including the link. {'Emoji allowed sparingly.' if emoji else 'No emoji.'} "
        "Never reuse the article's opening paragraph verbatim; no 'excited/thrilled to share'; no engagement bait."
    )
    out, _ = await structured(
        ctx, agent="linkedin", task="post", system=system, prompt=prompt, schema=LinkedInOut, validate=validate,
        context={"article": art, "link": link, "keyword": seo.get("primary_keyword")}, prompt_version=versions_tag(used),
    )
    tags = social_rules.normalize_hashtags(out.hashtags)
    text = social_rules.fit_length(out.hook, out.body, out.leaders_line, out.cta, link, tags, emoji=emoji)
    async with session_factory()() as db:
        post = SocialPost(
            id=uuid.uuid4(),
            tenant_id=ctx.tenant.id,
            article_id=article_id,
            platform="linkedin",
            text=text,
            hook=out.hook,
            cta=out.cta,
            link=link,
            hashtags=tags,
            image_url=(seo.get("og") or {}).get("image"),
            image_spec={"width": 1200, "height": 627, "title": art.get("title"), "kicker": art.get("category"), "brand": ctx.tenant.name},
            status="draft_ready",
        )
        db.add(post)
        audit(db, tenant_id=ctx.tenant.id, actor_type="agent", actor_id="distribution", action="social.generated",
              entity="social_post", entity_id=post.id, detail={"chars": len(text)})
        await db.commit()
        pid = post.id
    await ctx.log(f"LinkedIn draft ready ({len(text)} chars, {len(tags)} hashtag(s))")
    return {"social_post_id": str(pid), "chars": len(text)}


async def valid_token(db, tenant: Tenant) -> tuple[str | None, str | None, str]:
    """Return (access_token, author_urn, reason). Refreshes proactively at 80% of token life."""
    cfg = integration_config(tenant)["linkedin"]
    token = await get_secret(db, tenant.id, "linkedin_access_token")
    state = await linkedin_state(db, tenant.id)
    if not token:
        return None, None, "LinkedIn is not connected (no access token)"
    expires_at = datetime.fromisoformat(state["expires_at"]) if state.get("expires_at") else None
    issued_at = datetime.fromisoformat(state["issued_at"]) if state.get("issued_at") else None
    now = datetime.now(UTC)
    if expires_at and issued_at and now > issued_at + (expires_at - issued_at) * 0.8:
        refresh_token = await get_secret(db, tenant.id, "linkedin_refresh_token")
        secret = await get_secret(db, tenant.id, "linkedin_client_secret")
        if refresh_token and secret and cfg.get("client_id"):
            try:
                data = await linkedin.refresh(refresh_token, cfg["client_id"], secret)
                token = data["access_token"]
                await set_secret(db, tenant.id, "linkedin_access_token", token)
                if data.get("refresh_token"):
                    await set_secret(db, tenant.id, "linkedin_refresh_token", data["refresh_token"])
                state.update({"issued_at": now.isoformat(), "expires_at": data["expires_at"], "last_refresh_error": None})
                await set_linkedin_state(db, tenant.id, state)
                await db.commit()
            except linkedin.LinkedInError as exc:
                state["last_refresh_error"] = str(exc)
                await set_linkedin_state(db, tenant.id, state)
                await db.commit()
        if expires_at and now >= expires_at:
            return None, None, "LinkedIn token expired; reconnect in Settings → Integrations"
    author = state.get("author_urn")
    if cfg.get("author_type") == "organization" and cfg.get("org_urn"):
        author = cfg["org_urn"]
    if not author:
        return None, None, "No LinkedIn author URN (connect again, or set the organization URN)"
    return token, author, "ok"


async def run_distribute(ctx: AgentContext, social_post_id: uuid.UUID) -> dict[str, Any]:
    async with session_factory()() as db:
        post = await db.get(SocialPost, social_post_id)
        if post is None:
            raise PermanentError("Social post not found")
        if post.status == "published":
            return {"status": "already_published", "urn": post.remote_urn}
        tenant = await db.get(Tenant, post.tenant_id)
        article = await db.get(Article, post.article_id)
        token, author, reason = await valid_token(db, tenant)
        if token is None:
            post.status = "draft_ready"
            post.last_error = reason
            await db.commit()
            raise PermanentError(reason)
        post.status = "publishing"
        await db.commit()
        text, link, title = post.text, post.link, article.title if article else None
    try:
        urn = await linkedin.create_post(token, author, text, link=link, title=title)
    except linkedin.LinkedInError as exc:
        async with session_factory()() as db:
            post = await db.get(SocialPost, social_post_id)
            post.status = "failed" if not exc.retryable else "draft_ready"
            post.last_error = str(exc)[:1000]
            await db.commit()
        if exc.retryable:
            raise RetryableError(str(exc)) from exc
        raise PermanentError(str(exc)) from exc
    async with session_factory()() as db:
        post = await db.get(SocialPost, social_post_id)
        post.status = "published"
        post.remote_urn = urn
        post.published_at = utcnow()
        post.last_error = None
        audit(db, tenant_id=post.tenant_id, actor_type="agent", actor_id="distribution", action="social.published",
              entity="social_post", entity_id=post.id, detail={"urn": urn})
        await db.commit()
    await ctx.log(f"Posted to LinkedIn: {urn}")
    return {"status": "published", "urn": urn}


def token_expiry_from(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


__all__ = ["run_social_generate", "run_distribute", "valid_token"]
