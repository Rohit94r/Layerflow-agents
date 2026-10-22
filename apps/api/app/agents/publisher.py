"""A8 Publisher — idempotent delivery through adapters (plan §14). Never publishes unapproved content.
Idempotency key = sha256(tenant + slug + content_hash); re-publishing an edited version updates the same
remote page instead of creating a second URL. Every publish also writes an export bundle as a backup."""

from __future__ import annotations

import copy
import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError, PublishContext, PublishResult
from app.adapters.export_bundle import ExportBundleAdapter
from app.adapters.ten_static import TenStaticAdapter
from app.adapters.webhook import WebhookAdapter
from app.adapters.wordpress import WordPressAdapter
from app.agents.base import AgentContext
from app.core.audit import audit
from app.core.db import session_factory, utcnow
from app.models import Article, ArticleVersion, Publication, SitePage, SocialPost, Tenant
from app.queue.jobs import PermanentError, RetryableError, enqueue
from app.services import seo_rules
from app.services.article_doc import content_hash
from app.services.integrations import get_secret, integration_config
from app.services.playbooks import get_playbook
from app.services.render import render_article, validate_html
from app.services.tenant_settings import effective
from app.services.versions import add_version

PUBLISHABLE_STATES = frozenset({"approved", "scheduled", "publishing", "published"})
LATE_AFTER = timedelta(minutes=15)


def idempotency_key(tenant_slug: str, slug: str, chash: str, target: str = "") -> str:
    """sha256(tenant + slug + content_hash), plus the target so one version can go to two targets."""
    return hashlib.sha256(f"{tenant_slug}:{slug}:{chash}:{target}".encode()).hexdigest()


def adapter_for(target: str, fetcher: Any = None):
    if target == "ten_static":
        return TenStaticAdapter(fetcher)
    if target == "wordpress":
        return WordPressAdapter()
    if target == "webhook":
        return WebhookAdapter()
    if target == "export":
        return ExportBundleAdapter()
    raise PermanentError(f"Unknown publish target '{target}'")


def finalize_payload(payload: dict[str, Any], tenant: Tenant, published_at: datetime, modified_at: datetime | None = None) -> dict[str, Any]:
    """Stamp dates into JSON-LD at publish time (SEO agent leaves them empty)."""
    out = copy.deepcopy(payload)
    seo = out.get("seo") or {}
    art = out.get("article") or {}
    eff = effective(tenant.settings)
    brand = eff.get("brand", {})
    site_url = (brand.get("site_url") or "").rstrip("/")
    if seo:
        seo["json_ld"] = seo_rules.build_json_ld(
            headline=seo.get("h1") or art.get("title", ""),
            description=seo.get("meta_description", ""),
            url=seo.get("canonical_url") or seo_rules.canonical_for(site_url, art.get("category", "brief"), seo.get("slug", "")),
            category=art.get("category", "brief"),
            site_url=site_url,
            brand_name=brand.get("name", tenant.name),
            logo_url=brand.get("logo_url", ""),
            image_url=(seo.get("og") or {}).get("image"),
            author_name=brand.get("author_name", "Editorial"),
            published_at=published_at,
            modified_at=modified_at or published_at,
            keywords=[seo.get("primary_keyword", ""), *(seo.get("secondary_keywords") or [])],
        )
        out["seo"] = seo
    return out


async def build_context(
    db: AsyncSession,
    *,
    tenant: Tenant,
    article: Article,
    payload: dict[str, Any],
    target: str,
    published_at: datetime,
    modified_at: datetime | None = None,
) -> PublishContext:
    seo = payload.get("seo") or {}
    art = payload.get("article") or {}
    if not seo.get("slug"):
        raise PermanentError("Run the SEO stage before publishing (no slug)")
    eff = effective(tenant.settings)
    final = finalize_payload(payload, tenant, published_at, modified_at)
    html = render_article(final, brand=eff.get("brand", {}), published_at=published_at, timezone=tenant.timezone, spelling=eff.get("spelling", "en-US"))
    integ = integration_config(tenant)
    config = dict(integ.get(target) or {})
    secrets: dict[str, str | None] = {}
    for key in ("wordpress_app_password", "webhook_secret", "ten_sftp_password"):
        secrets[key] = await get_secret(db, tenant.id, key)
    inventory = list(
        (
            await db.execute(
                select(SitePage.url).where(SitePage.tenant_id == tenant.id, SitePage.site == "own", SitePage.status_code == 200)
            )
        ).scalars()
    )
    pb = get_playbook(art.get("category", article.category))
    return PublishContext(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        article_id=article.id,
        category=pb.key,
        route=pb.route,
        slug=seo["slug"],
        content_hash=content_hash(final),
        payload=final,
        html=html,
        published_at=published_at,
        site_url=(eff.get("brand", {}).get("site_url") or integ["ten_static"]["site_url"]).rstrip("/"),
        config=config,
        secrets=secrets,
        inventory_urls=inventory,
    )


async def preview(db: AsyncSession, *, tenant: Tenant, article: Article, target: str, fetcher: Any = None) -> dict[str, Any]:
    """Dry run: render + validate + adapter dry run. Touches nothing on any server."""
    v = await db.get(ArticleVersion, article.current_version_id) if article.current_version_id else None
    if v is None:
        raise PermanentError("Article has no content yet")
    pctx = await build_context(db, tenant=tenant, article=article, payload=v.payload, target=target, published_at=utcnow())
    adapter = adapter_for(target, fetcher)
    issues = validate_html(pctx.html, expected_h1=(pctx.payload.get("seo") or {}).get("h1"))
    issues += await adapter.validate(pctx)
    result: PublishResult | None = None
    try:
        result = await adapter.publish(pctx, dry_run=True)
    except AdapterError as exc:
        issues.append(str(exc))
    existing = (
        await db.execute(
            select(Publication).where(Publication.article_id == article.id, Publication.target == target, Publication.status == "published")
            .order_by(Publication.published_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return {
        "target": target,
        "html": pctx.html,
        "issues": sorted(set(issues)),
        "files": result.artifacts if result else [],
        "live_url": result.live_url if result else None,
        "content_hash": pctx.content_hash,
        "idempotency_key": idempotency_key(tenant.slug, pctx.slug, article.content_hash or pctx.content_hash, target),
        "will_update": existing is not None,
        "existing_live_url": existing.live_url if existing else None,
        "unchanged": bool(existing and existing.content_hash == pctx.content_hash),
        "preview": result.preview if result else None,
    }


async def run_publish(ctx: AgentContext, publication_id: uuid.UUID) -> dict[str, Any]:
    async with session_factory()() as db:
        pub = await db.get(Publication, publication_id)
        if pub is None:
            raise PermanentError("Publication not found")
        if pub.status == "cancelled":
            raise PermanentError("Publication was cancelled")
        article = await db.get(Article, pub.article_id)
        tenant = await db.get(Tenant, pub.tenant_id)
        if article is None or tenant is None:
            raise PermanentError("Article missing")
        if article.state not in PUBLISHABLE_STATES:
            raise PermanentError(f"Article is '{article.state}'; only approved articles can be published")
        version = await db.get(ArticleVersion, pub.version_id or article.current_version_id)
        if version is None:
            raise PermanentError("No approved version to publish")
        previous = (
            await db.execute(
                select(Publication)
                .where(
                    Publication.article_id == article.id,
                    Publication.target == pub.target,
                    Publication.status == "published",
                    Publication.id != pub.id,
                )
                .order_by(Publication.published_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if pub.status == "published" and pub.content_hash:
            return {"status": "already_published", "live_url": pub.live_url}
        first_published = previous.published_at if previous and previous.published_at else None
        now = utcnow()
        pctx = await build_context(
            db, tenant=tenant, article=article, payload=version.payload, target=pub.target,
            published_at=first_published or now, modified_at=now,
        )
        if previous is not None and previous.content_hash == pctx.content_hash:
            # Same content already live: idempotent no-op, never a duplicate page.
            pub.status = "published"
            pub.published_at = previous.published_at
            pub.live_url = previous.live_url
            pub.remote_id = previous.remote_id
            pub.content_hash = pctx.content_hash
            pub.warnings = ["Identical content already published; nothing re-uploaded"]
            if article.state != "published":
                from app.agents.orchestrator import transition

                for step in ("scheduled", "publishing", "published"):
                    if article.state != "published":
                        try:
                            await transition(db, article, step, reason="idempotent re-publish")
                        except Exception:
                            pass
            await db.commit()
            return {"status": "unchanged", "live_url": pub.live_url}
        from app.agents.orchestrator import transition

        if article.state == "approved":
            await transition(db, article, "scheduled", reason="publish now")
        if article.state in ("scheduled", "published"):
            await transition(db, article, "publishing", reason=f"publishing to {pub.target}")
        pub.status = "publishing"
        await db.commit()

    await ctx.log(f"Publishing to {pub.target} ({'update' if previous else 'new page'})")
    adapter = adapter_for(pub.target, ctx.fetcher)
    try:
        if previous is not None and previous.remote_id:
            result = await adapter.update(previous.remote_id, pctx)
        else:
            result = await adapter.publish(pctx)
    except AdapterError as exc:
        if exc.retryable:
            raise RetryableError(str(exc)) from exc
        raise PermanentError(str(exc)) from exc

    backup = None
    if pub.target != "export":
        try:
            backup = await ExportBundleAdapter().publish(pctx)
        except OSError as exc:
            result.warnings.append(f"Backup bundle not written: {exc}")

    async with session_factory()() as db:
        pub = await db.get(Publication, publication_id)
        article = await db.get(Article, pub.article_id)
        version = await db.get(ArticleVersion, pub.version_id or article.current_version_id)
        published_at = utcnow()
        pub.status = "published"
        pub.published_at = published_at
        pub.remote_id = result.remote_id
        pub.live_url = result.live_url
        pub.content_hash = pctx.content_hash
        pub.artifact_path = result.artifact_path or (backup.artifact_path if backup else None)
        pub.warnings = result.warnings
        pub.last_error = None
        pub.late = bool(pub.scheduled_at and published_at - pub.scheduled_at > LATE_AFTER)
        if pub.late:
            pub.warnings = [*pub.warnings, "Published late (scheduled window was missed; published once on recovery)"]
        from app.agents.orchestrator import transition

        await transition(db, article, "published", reason=f"live at {result.live_url}")
        article.published_url = result.live_url
        await add_version(db, article, stage="published", payload=pctx.payload, note=f"Published to {pub.target}: {result.live_url}")
        audit(db, tenant_id=pub.tenant_id, actor_type="agent", actor_id="publisher", action="publication.published",
              entity="publication", entity_id=pub.id, detail={"target": pub.target, "live_url": result.live_url, "late": pub.late})
        has_post = (await db.execute(select(SocialPost.id).where(SocialPost.article_id == article.id).limit(1))).scalar_one_or_none()
        if has_post is None:
            await enqueue(db, tenant_id=pub.tenant_id, type="social", payload={"article_id": str(article.id)}, article_id=article.id)
        await db.commit()
    await ctx.log(f"Live: {result.live_url}" + (f" — {'; '.join(result.warnings)}" if result.warnings else ""))
    return {"status": "published", "live_url": result.live_url, "warnings": result.warnings, "late": pub.late}


async def on_publish_failed(publication_id: uuid.UUID, error: str) -> None:
    async with session_factory()() as db:
        pub = await db.get(Publication, publication_id)
        if pub is None:
            return
        pub.status = "failed"
        pub.last_error = error[:2000]
        article = await db.get(Article, pub.article_id)
        if article is not None and article.state == "publishing":
            from app.agents.orchestrator import transition

            prior = (
                await db.execute(select(Publication.id).where(Publication.article_id == article.id, Publication.status == "published").limit(1))
            ).scalar_one_or_none()
            await transition(db, article, "published" if prior else "approved", reason="publish failed")
        audit(db, tenant_id=pub.tenant_id, actor_type="agent", actor_id="publisher", action="publication.failed",
              entity="publication", entity_id=pub.id, detail={"error": error[:500]})
        await db.commit()


async def rollback(db: AsyncSession, pub: Publication, fetcher: Any = None) -> None:
    article = await db.get(Article, pub.article_id)
    tenant = await db.get(Tenant, pub.tenant_id)
    version = await db.get(ArticleVersion, pub.version_id or article.current_version_id)
    pctx = await build_context(db, tenant=tenant, article=article, payload=version.payload, target=pub.target, published_at=pub.published_at or utcnow())
    try:
        await adapter_for(pub.target, fetcher).unpublish(pub.remote_id or "", pctx)
    except AdapterError as exc:
        raise PermanentError(str(exc)) from exc
    pub.status = "rolled_back"
