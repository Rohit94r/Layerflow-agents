"""SEO workspace endpoints (plan §8.5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import orchestrator
from app.agents.crawl import load_competitors, topic_terms
from app.agents.state import IllegalTransition
from app.core.audit import audit
from app.core.config import get_settings
from app.core.deps import ROLE_CONTENT, Principal, current_principal, get_db, require
from app.core.errors import ApiError, conflict
from app.models import Article, SitePage, Tenant
from app.queue.jobs import enqueue
from app.routers.common import owned, page_params, paginated
from app.schemas import SeoPatch
from app.serializers import job_out, site_page_out
from app.services import seo_rules, site_audit, sitemap
from app.services.integrations import kv_get
from app.services.slug import validate_slug
from app.services.tenant_settings import effective
from app.services.versions import add_version, current_payload

router = APIRouter(prefix="/seo", tags=["seo"])


async def _pages(db: AsyncSession, tenant_id, site: str = "own") -> list[SitePage]:
    return list((await db.execute(select(SitePage).where(SitePage.tenant_id == tenant_id, SitePage.site == site))).scalars())


@router.get("/inventory")
async def inventory(
    site: str = "own", q: str | None = None, page: int = 1, page_size: int = 100,
    principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db),
):
    page, page_size, offset = page_params(page, page_size, 500)
    query = select(SitePage).where(SitePage.tenant_id == principal.tenant_id, SitePage.site == site)
    if q:
        query = query.where(SitePage.url.ilike(f"%{q}%") | SitePage.title.ilike(f"%{q}%") | SitePage.headline.ilike(f"%{q}%"))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (await db.execute(query.order_by(SitePage.url).offset(offset).limit(page_size))).scalars().all()
    state = await kv_get(db, principal.tenant_id, "seo.inventory") or {}
    out = paginated([site_page_out(p) for p in rows], total, page, page_size)
    out["crawled_at"] = state.get("crawled_at")
    out["sitemap"] = state.get("sitemap")
    return out


@router.post("/inventory/refresh")
async def refresh_inventory(principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    job = await enqueue(db, tenant_id=principal.tenant_id, type="crawl_inventory", payload={"max_pages": 250}, dedupe_key="crawl:own", created_by=principal.user.id)
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="seo.audit_run", entity="seo")
    await db.commit()
    return {"job": job_out(job)}


@router.get("/audit")
async def get_audit(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    pages = await _pages(db, principal.tenant_id)
    state = await kv_get(db, principal.tenant_id, "seo.inventory")
    tenant = await db.get(Tenant, principal.tenant_id)
    brand = effective(tenant.settings).get("brand", {})
    result = site_audit.audit(pages, state)
    fixes = site_audit.fix_list(pages, brand.get("site_url") or get_settings().ten_site_url, brand.get("short_name", "TEN"))
    result["fix_list"] = fixes[:500]
    result["fix_count"] = len(fixes)
    return result


@router.get("/audit/export")
async def export_fix_list(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    pages = await _pages(db, principal.tenant_id)
    tenant = await db.get(Tenant, principal.tenant_id)
    brand = effective(tenant.settings).get("brand", {})
    rows = site_audit.fix_list(pages, brand.get("site_url") or get_settings().ten_site_url, brand.get("short_name", "TEN"))
    return Response(
        site_audit.fix_list_csv(rows),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{tenant.slug}-seo-fix-list.csv"'},
    )


@router.get("/audit/sitemap", response_class=PlainTextResponse)
async def corrected_sitemap(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    pages = await _pages(db, principal.tenant_id)
    tenant = await db.get(Tenant, principal.tenant_id)
    site_url = effective(tenant.settings).get("brand", {}).get("site_url") or get_settings().ten_site_url
    published = (
        await db.execute(select(Article.slug, Article.category, Article.updated_at).where(Article.tenant_id == tenant.id, Article.state == "published"))
    ).all()
    entries: dict[str, Any] = {p.url: None for p in pages if p.status_code == 200}
    for slug, category, updated in published:
        if slug:
            entries[seo_rules.canonical_for(site_url, category, slug)] = updated
    xml, _ = sitemap.merge(None, site_url, entries)
    return Response(xml, media_type="application/xml", headers={"Content-Disposition": 'attachment; filename="sitemap.xml"'})


@router.get("/competitors")
async def competitors(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    comps = load_competitors(get_settings().config_dir / "competitors.yaml")
    state = await kv_get(db, principal.tenant_id, "seo.competitors") or {}
    own = await _pages(db, principal.tenant_id)
    own_terms = {t for t, _ in topic_terms([" ".join(filter(None, [p.title, p.headline, p.first_paragraph])) for p in own], top=400)}
    published = (await db.execute(select(Article.title).where(Article.tenant_id == principal.tenant_id, Article.state == "published"))).scalars().all()
    own_terms |= {t for t, _ in topic_terms(list(published), top=200)}
    items = []
    for c in comps:
        pages = await _pages(db, principal.tenant_id, c["key"])
        texts = [" ".join(filter(None, [p.title, p.headline, p.first_paragraph, " ".join(p.headings or [])])) for p in pages]
        terms = topic_terms(texts, top=30)
        wcs = [p.word_count for p in pages if p.word_count]
        items.append(
            {
                **{k: c.get(k) for k in ("key", "name", "site", "sitemap", "max_pages")},
                "last_crawled_at": (state.get(c["key"]) or {}).get("crawled_at"),
                "pages": len(pages),
                "avg_word_count": int(sum(wcs) / len(wcs)) if wcs else None,
                "jsonld_share": round(sum(1 for p in pages if p.has_jsonld) / len(pages), 2) if pages else None,
                "top_terms": [{"term": t, "pages": n} for t, n in terms[:15]],
                "gaps": [t for t, n in terms if t not in own_terms and n >= 2][:12],
                "sample": [{"url": p.url, "title": p.headline or p.title, "word_count": p.word_count} for p in pages[:8]],
            }
        )
    return {"items": items, "own_pages": len(own)}


@router.post("/competitors/refresh")
async def refresh_competitors(principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    job = await enqueue(db, tenant_id=principal.tenant_id, type="crawl_competitors", payload={}, dedupe_key="crawl:competitors", created_by=principal.user.id)
    await db.commit()
    return {"job": job_out(job)}


@router.get("/{article_id}")
async def get_seo(article_id: str, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    payload = await current_payload(db, article)
    seo = payload.get("seo")
    return {
        "article": {"id": str(article.id), "title": article.title, "category": article.category, "state": article.state, "slug": article.slug},
        "seo": seo,
        "issues": (seo or {}).get("issues", []),
        "h1": ((payload.get("article") or {}).get("title")),
        "dek": ((payload.get("article") or {}).get("dek")),
    }


@router.patch("/{article_id}")
async def patch_seo(article_id: str, body: SeoPatch, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    if await orchestrator.active_job(db, article.id):
        raise conflict("busy", "An agent is working on this article")
    if article.state in ("scheduled", "publishing"):
        raise conflict("illegal_transition", "Cancel the scheduled publication before changing SEO")
    payload = await current_payload(db, article)
    seo = dict(payload.get("seo") or {})
    if not seo:
        raise conflict("seo_missing", "Run the SEO stage first")
    changes = body.model_dump(exclude_unset=True)
    tenant = await db.get(Tenant, principal.tenant_id)
    brand = effective(tenant.settings).get("brand", {})
    site_url = (brand.get("site_url") or get_settings().ten_site_url).rstrip("/")
    h1 = changes.get("h1") or seo.get("h1") or (payload.get("article") or {}).get("title", "")
    problems: list[str] = []
    if "title_tag" in changes:
        problems += seo_rules.validate_title_tag(changes["title_tag"], h1=h1)
    if "meta_description" in changes:
        problems += seo_rules.validate_meta(changes["meta_description"])
    if "slug" in changes:
        problems += validate_slug(changes["slug"])
        taken = set(
            (await db.execute(select(Article.slug).where(Article.tenant_id == tenant.id, Article.id != article.id, Article.slug.is_not(None)))).scalars()
        )
        if changes["slug"] in taken:
            problems.append("Slug is already used by another article")
        published_before = article.published_url is not None
        if published_before and changes["slug"] != seo.get("slug"):
            problems.append("Slug cannot change after publishing (it would break the live URL)")
    if "h1" in changes:
        problems += seo_rules.validate_h1(changes["h1"])
    if problems:
        raise ApiError(422, "seo_invalid", "Override rejected by the SEO rules", problems)
    seo.update({k: v for k, v in changes.items() if v is not None})
    seo["canonical_url"] = changes.get("canonical_url") or seo_rules.canonical_for(site_url, article.category, seo["slug"])
    seo["og"] = {**(seo.get("og") or {}), "title": seo["title_tag"], "description": seo["meta_description"], "url": seo["canonical_url"]}
    seo["twitter"] = {**(seo.get("twitter") or {}), "title": seo["title_tag"], "description": seo["meta_description"]}
    seo["json_ld"] = seo_rules.build_json_ld(
        headline=seo.get("h1") or h1, description=seo["meta_description"], url=seo["canonical_url"], category=article.category,
        site_url=site_url, brand_name=brand.get("name", tenant.name), logo_url=brand.get("logo_url", ""), image_url=seo["og"].get("image"),
        author_name=brand.get("author_name", "Editorial"), published_at=None, modified_at=None,
        keywords=[seo.get("primary_keyword", ""), *(seo.get("secondary_keywords") or [])],
    )
    seo["overrides"] = sorted(set(seo.get("overrides") or []) | set(changes))
    issues = seo_rules.full_issues(seo)
    seo["issues"], seo["score"] = issues, seo_rules.seo_score(seo, issues)
    seo["fields_complete"], _ = seo_rules.completeness(seo)
    qa = payload.get("qa")
    if qa:
        qa = {**qa, "stale_seo": True}
    await add_version(db, article, stage="seo", payload={**payload, "seo": seo, "qa": qa}, created_by=principal.user.id, note=f"Manual SEO override: {', '.join(changes)}")
    if article.state == "published":
        try:
            await orchestrator.transition(db, article, "in_review", actor_type="user", actor_id=principal.user.id, reason="SEO changed after publishing; re-approve to republish")
        except IllegalTransition:
            pass
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="seo.override", entity="article", entity_id=article.id, detail={"fields": list(changes)})
    await db.commit()
    return {"seo": seo, "issues": issues}


@router.post("/{article_id}/regenerate")
async def regenerate(article_id: str, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    article = await owned(db, Article, article_id, principal.tenant_id, "article")
    try:
        job = await orchestrator.start_stage(db, article, "seo", auto=False, user_id=principal.user.id)
    except IllegalTransition as exc:
        raise conflict("illegal_transition", str(exc)) from exc
    await db.commit()
    return {"job": job_out(job)}

