"""A5 SEO — search intent, metadata, slug, internal links, schema and social preview. Rules decide; the model
only proposes phrasing for the title tag and meta description, and every proposal is validated in code."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.base import AgentContext, AgentOutputError, structured
from app.core.db import session_factory, utcnow
from app.models import Article, ArticleVersion, SitePage
from app.queue.jobs import PermanentError
from app.services import seo_rules
from app.services.article_doc import body_text, prose_text
from app.services.dedupe import TfidfIndex
from app.services.fetcher import FetchError
from app.services.playbooks import get_playbook
from app.services.prompts import compose_system, versions_tag
from app.services.search import autosuggest
from app.services.slug import slugify, unique_slug, validate_slug
from app.services.text import readability, truncate_words
from app.services.versions import add_version, current_payload


class SeoCopy(BaseModel):
    title_tags: list[str] = Field(min_length=1, max_length=3, description="30–60 characters each, primary keyword early")
    meta_descriptions: list[str] = Field(min_length=1, max_length=3, description="140–158 characters each")
    primary_keyword: str = Field(min_length=3, max_length=60)
    secondary_keywords: list[str] = Field(default_factory=list, max_length=6)


async def _inventory(db, tenant_id: uuid.UUID, exclude_article: uuid.UUID) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    pages = list((await db.execute(select(SitePage).where(SitePage.tenant_id == tenant_id, SitePage.site == "own"))).scalars())
    items = [
        {
            "url": p.url,
            "title": p.headline or p.h1 or p.title,
            "text": " ".join(filter(None, [p.headline, p.h1, p.title, p.first_paragraph])),
            "status": p.status_code,
            "source": "inventory",
        }
        for p in pages
    ]
    taken_slugs = {urlsplit(p.url).path.rstrip("/").split("/")[-1].lower() for p in pages}
    taken_titles = {(p.title or "").strip().lower() for p in pages if p.title and "the executive narrative" not in p.title.lower()}
    others = list(
        (
            await db.execute(
                select(Article).where(Article.tenant_id == tenant_id, Article.id != exclude_article, Article.slug.is_not(None))
            )
        ).scalars()
    )
    for a in others:
        taken_slugs.add(a.slug)
        if a.state == "published" and a.published_url:
            v = await db.get(ArticleVersion, a.current_version_id) if a.current_version_id else None
            dek = ((v.payload or {}).get("article") or {}).get("dek", "") if v else ""
            items.append({"url": a.published_url, "title": a.title, "text": f"{a.title} {dek}", "status": 200, "source": "published"})
            seo = (v.payload or {}).get("seo") if v else None
            if seo and seo.get("title_tag"):
                taken_titles.add(seo["title_tag"].strip().lower())
    return items, taken_slugs, taken_titles


def _pick(candidates: list[str], check) -> str | None:
    for c in candidates:
        c = (c or "").strip().strip('"').strip()
        if c and not check(c):
            return c
    return None


async def run_seo(ctx: AgentContext, article_id: uuid.UUID, *, instruction: str | None = None) -> dict[str, Any]:
    brand = ctx.tenant.settings.get("brand", {})
    site_url = (brand.get("site_url") or ctx.settings.ten_site_url).rstrip("/")
    async with session_factory()() as db:
        article = await db.get(Article, article_id)
        if article is None:
            raise PermanentError("Article missing")
        payload = await current_payload(db, article)
        art = payload.get("article")
        if not art:
            raise PermanentError("Nothing to optimise yet; run Write first")
        inventory, taken_slugs, taken_titles = await _inventory(db, ctx.tenant.id, article_id)
        system, used = await compose_system(db, ctx.tenant.id, agent="seo", include_persona=False, include_style=False)
        previous_seo = payload.get("seo") or {}

    pb = get_playbook(art["category"])
    h1 = art["title"]
    body = body_text(art)
    candidates = seo_rules.extract_keywords(h1, body, top=8)
    suggestions = await autosuggest(ctx.fetcher, candidates[0]) if candidates else []

    prompt = (
        f"Article title (this is the H1; your title tags must differ from it): {h1}\n"
        f"Dek: {art.get('dek', '')}\nCategory: {pb.label}\n"
        f"Takeaway: {art.get('takeaway', '')}\n"
        f"Keyword candidates from the article: {', '.join(candidates)}\n"
        + (f"Search autosuggest for '{candidates[0]}': {', '.join(suggestions)}\n" if suggestions else "")
        + (f"Editor's instruction: {instruction}\n" if instruction else "")
        + f"\nPropose up to 3 title tags ({seo_rules.TITLE_MIN}–{seo_rules.TITLE_MAX} characters, primary keyword early, no clickbait, "
        f"no brand suffix) and up to 3 meta descriptions ({seo_rules.META_MIN}–{seo_rules.META_MAX} characters, one value proposition "
        "+ one specific detail from the article, active voice, never 'learn more'). Pick the primary keyword from the candidates "
        "and up to 5 secondary keywords."
    )
    copy_out: SeoCopy | None = None
    try:
        copy_out, _ = await structured(
            ctx, agent="seo", task="meta", system=system, prompt=prompt, schema=SeoCopy,
            context={"title": h1, "dek": art.get("dek", ""), "keywords": candidates, "category": art["category"], "takeaway": art.get("takeaway", "")},
            prompt_version=versions_tag(used), max_repairs=1,
        )
    except AgentOutputError as exc:
        await ctx.log(f"SEO copy fell back to deterministic rules ({str(exc)[:100]})", level="warn")

    primary = (copy_out.primary_keyword.strip().lower() if copy_out else "") or (candidates[0] if candidates else h1.split()[0].lower())
    secondary = [k.lower().strip() for k in (copy_out.secondary_keywords if copy_out else candidates[1:6]) if k and k.lower() != primary][:5]

    def title_check(t: str) -> list[str]:
        return seo_rules.validate_title_tag(t, h1=h1, taken=taken_titles)

    title_candidates = list(copy_out.title_tags if copy_out else [])
    title_candidates += [
        seo_rules.fit_title(f"{primary.title()}: {h1}"),
        seo_rules.fit_title(f"{h1.split(':')[0]}: What It Means for Leaders"),
        seo_rules.fit_title(f"{h1} — {pb.label}"),
        seo_rules.fit_title(f"{primary.title()} — {pb.label} Analysis"),
    ]
    title_tag = _pick(title_candidates, title_check) or seo_rules.fit_title(f"{primary.title()}: {pb.label} for Leaders")

    meta_candidates = list(copy_out.meta_descriptions if copy_out else [])
    dek = art.get("dek", "")
    first_para = next((p for s in art["sections"] for p in s.get("paragraphs") or []), "")
    for extra in (f"{dek} {first_para}", f"{dek} {art.get('takeaway', '')}", f"{first_para} {dek}"):
        meta_candidates.append(seo_rules.fit_meta(extra))
    meta = _pick(meta_candidates, seo_rules.validate_meta) or seo_rules.fit_meta(f"{dek} {first_para}")

    base_slug = previous_seo.get("slug") if previous_seo.get("slug") and not validate_slug(previous_seo["slug"]) else slugify(h1)
    slug = base_slug if base_slug == previous_seo.get("slug") else unique_slug(base_slug, taken_slugs)
    canonical = seo_rules.canonical_for(site_url, art["category"], slug)

    # Internal links: similarity against the inventory + published articles, verified before use.
    internal: list[dict[str, Any]] = []
    if inventory:
        idx = TfidfIndex([i["text"] for i in inventory] + [f"{h1} {art.get('dek', '')} {body[:3000]}"])
        me = idx.vectors[-1]
        scored = sorted(
            ((TfidfIndex.cosine(me, idx.vectors[i]), inv) for i, inv in enumerate(inventory)),
            key=lambda x: x[0],
            reverse=True,
        )
        for sim, inv in scored:
            if len(internal) >= 6 or sim < 0.06:
                break
            if inv["url"].rstrip("/") == canonical.rstrip("/"):
                continue
            valid = inv["status"] == 200
            status = inv["status"]
            if inv["source"] == "inventory" and valid:
                try:
                    res = await ctx.fetcher.get(inv["url"], respect_robots=False, use_cache=True)
                    status, valid = res.status, res.status == 200
                except FetchError as exc:
                    status, valid = exc.status, False
            internal.append(
                {
                    "url": inv["url"],
                    "title": inv["title"],
                    "anchor": truncate_words(inv["title"] or "", 70),
                    "similarity": round(sim, 3),
                    "valid": valid,
                    "status_code": status,
                }
            )
        internal = [l for l in internal if l["valid"]][:6] + [l for l in internal if not l["valid"]][:2]
    sources_meta = {s["url"]: s for s in payload.get("sources_meta") or []}
    external = [
        {"url": u, "title": (sources_meta.get(u) or {}).get("title"), "publisher": (sources_meta.get(u) or {}).get("publisher")}
        for u in art.get("sources_used") or []
        if u.startswith("http")
    ]
    image = brand.get("og_image_url") or brand.get("logo_url")
    og = {
        "title": title_tag,
        "description": meta,
        "url": canonical,
        "image": image,
        "type": "article",
        "site_name": brand.get("name", "The Executive Narrative"),
        "locale": "en_GB" if ctx.tenant.settings.get("spelling") == "en-GB" else "en_US",
    }
    twitter = {"card": "summary_large_image", "title": title_tag, "description": meta, "image": image}
    json_ld = seo_rules.build_json_ld(
        headline=h1, description=meta, url=canonical, category=art["category"], site_url=site_url,
        brand_name=brand.get("name", "The Executive Narrative"), logo_url=brand.get("logo_url", ""), image_url=image,
        author_name=brand.get("author_name", "The Executive Narrative Editorial"), published_at=None, modified_at=None,
        keywords=[primary, *secondary],
    )
    seo = {
        "title_tag": title_tag,
        "meta_description": meta,
        "slug": slug,
        "canonical_url": canonical,
        "h1": h1,
        "primary_keyword": primary,
        "secondary_keywords": secondary,
        "keyword_candidates": candidates,
        "autosuggest": suggestions,
        "search_intent": seo_rules.search_intent(art["category"], h1),
        "internal_links": internal,
        "external_links": external,
        "og": og,
        "twitter": twitter,
        "json_ld": json_ld,
        "readability": readability(prose_text(art)),
        "generated_at": utcnow().isoformat(),
        "overrides": [],
        "inventory_size": len(inventory),
    }
    issues = seo_rules.full_issues(seo, taken_titles=taken_titles)
    done, _missing = seo_rules.completeness(seo)
    seo["issues"] = issues
    seo["score"] = seo_rules.seo_score(seo, issues)
    seo["fields_complete"] = done
    seo["fields_total"] = len(seo_rules.REQUIRED_FIELDS)

    new_payload = {**payload, "seo": seo, "qa": None}
    async with session_factory()() as db:
        article = await db.get(Article, article_id)
        await add_version(db, article, stage="seo", payload=new_payload, prompt_version=versions_tag(used),
                          note=f"SEO score {seo['score']}, {done}/8 fields")
        article.prompt_versions = {**(article.prompt_versions or {}), "seo": versions_tag(used)}
        await db.commit()
    await ctx.log(f"SEO: “{title_tag}” ({len(title_tag)} chars), slug /{slug}, {len([l for l in internal if l['valid']])} verified internal link(s)")
    return {"score": seo["score"], "fields_complete": done, "issues": len(issues), "slug": slug}
