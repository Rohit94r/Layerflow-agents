"""Site inventory and competitor crawls (plan §13.1). Rate-limited, robots-respecting, public pages only."""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from sqlalchemy import select

from app.agents.base import AgentContext
from app.core.db import session_factory, utcnow
from app.models import SitePage
from app.queue.jobs import JobError
from app.services.fetcher import FetchError
from app.services.htmlmeta import parse_page, parse_sitemap
from app.services.integrations import kv_get, kv_set
from app.services.playbooks import PLAYBOOKS
from app.services.sitemap import valid_for_site
from app.services.text import content_tokens

ARTICLE_ROUTES = tuple(p.route.strip("/") for p in PLAYBOOKS.values()) + ("discover", "blog")


async def _sitemaps_from_robots(ctx: AgentContext, site: str) -> list[str]:
    try:
        res = await ctx.fetcher.get(site.rstrip("/") + "/robots.txt", respect_robots=False, use_cache=True, accept=("text/plain", "text/html"))
    except FetchError:
        return []
    return [ln.split(":", 1)[1].strip() for ln in res.text.splitlines() if ln.lower().startswith("sitemap:")]


async def _sitemap_urls(ctx: AgentContext, sitemap_url: str, *, depth: int = 0, limit: int = 2000) -> tuple[list[str], dict[str, Any]]:
    info: dict[str, Any] = {"url": sitemap_url, "status": None, "children": 0}
    try:
        res = await ctx.fetcher.get(sitemap_url, respect_robots=False, use_cache=False)
    except FetchError as exc:
        info["status"] = exc.status or "error"
        info["error"] = str(exc)
        return [], info
    info["status"] = res.status
    urls, children = parse_sitemap(res.text)
    info["children"] = len(children)
    if children and depth < 1:
        # Prefer post/article sitemaps; newest usually last.
        children.sort(key=lambda u: (not re.search(r"post|article|news|blog|insight", u, re.I), u))
        for child in children[:3]:
            more, _ = await _sitemap_urls(ctx, child, depth=depth + 1, limit=limit)
            urls.extend(more)
            if len(urls) >= limit:
                break
    return urls[:limit], info


async def crawl_inventory(ctx: AgentContext, *, max_pages: int = 250) -> dict[str, Any]:
    brand = ctx.tenant.settings.get("brand", {})
    site = (brand.get("site_url") or ctx.settings.ten_site_url).rstrip("/")
    host = urlsplit(site).hostname
    sitemap_url = f"{site}/sitemap.xml"
    sm_urls, sm_info = await _sitemap_urls(ctx, sitemap_url)
    invalid = [u for u in sm_urls if not valid_for_site(u, site)]
    valid = [u for u in sm_urls if valid_for_site(u, site)]
    sm_info.update({"urls": len(sm_urls), "valid": len(valid), "invalid": len(invalid), "invalid_sample": invalid[:5]})
    await ctx.log(f"Sitemap: {len(sm_urls)} URL(s), {len(invalid)} invalid (e.g. localhost)")

    # BFS over internal links (depth 2) when the sitemap is broken or thin.
    queue: deque[tuple[str, int]] = deque([(site + "/", 0)] + [(u, 1) for u in valid])
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    errors = 0
    stack: set[str] = set()
    while queue and len(pages) < max_pages:
        url, depth = queue.popleft()
        url = url.split("#")[0]
        if url in seen:
            continue
        seen.add(url)
        await ctx.beat()
        try:
            res = await ctx.fetcher.get(url, respect_robots=True, use_cache=False)
        except FetchError as exc:
            errors += 1
            pages.append({"url": url, "status": exc.status or 0, "meta": None})
            continue
        if not res.content_type.startswith("text/html"):
            continue
        meta = parse_page(res.text, res.final_url or url)
        stack.update(meta.stack_signals)
        pages.append({"url": res.final_url or url, "status": res.status, "meta": meta})
        if depth < 2:
            for link in meta.internal_links:
                if urlsplit(link).hostname != host or link in seen:
                    continue
                path = urlsplit(link).path.strip("/")
                if not path or path.split("/")[0] in ARTICLE_ROUTES or depth == 0:
                    queue.append((link, depth + 1))
        if len(pages) % 20 == 0:
            await ctx.log(f"Crawled {len(pages)} page(s)…")

    async with session_factory()() as db:
        existing = {p.url: p for p in (await db.execute(select(SitePage).where(SitePage.tenant_id == ctx.tenant.id, SitePage.site == "own"))).scalars()}
        for p in pages:
            row = existing.get(p["url"]) or SitePage(tenant_id=ctx.tenant.id, site="own", url=p["url"])
            meta = p["meta"]
            row.status_code = p["status"]
            row.fetched_at = utcnow()
            if meta is not None:
                row.title = meta.title
                row.h1 = meta.h1[0] if meta.h1 else None
                row.headline = meta.headline
                row.meta_description = meta.meta_description
                row.canonical = meta.canonical
                row.og = meta.og
                row.has_jsonld = meta.has_jsonld
                row.word_count = meta.word_count
                row.headings = meta.headings
                row.first_paragraph = meta.first_paragraph
                row.signals = {"placeholders": meta.placeholder_hits, "stack": meta.stack_signals, "h1_count": len(meta.h1), "twitter": len(meta.twitter)}
            if p["url"] not in existing:
                db.add(row)
        await kv_set(
            db, ctx.tenant.id, "seo.inventory",
            {"crawled_at": utcnow().isoformat(), "site": site, "sitemap": sm_info, "pages": len(pages), "errors": errors, "stack": sorted(stack)},
        )
        await db.commit()
    await ctx.log(f"Inventory: {len(pages)} page(s) stored, {errors} error(s)")
    return {"pages": len(pages), "errors": errors, "sitemap_urls": len(sm_urls), "sitemap_invalid": len(invalid)}


def load_competitors(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [c for c in data.get("competitors", []) if c.get("key") and c.get("site")]


async def crawl_competitors(ctx: AgentContext) -> dict[str, Any]:
    comps = load_competitors(ctx.settings.config_dir / "competitors.yaml")
    if not comps:
        raise JobError("No competitors configured in config/competitors.yaml")
    summary: dict[str, Any] = {}
    async with session_factory()() as db:
        state = await kv_get(db, ctx.tenant.id, "seo.competitors") or {}
    for comp in comps:
        site = comp["site"].rstrip("/")
        candidates = [comp["sitemap"]] if comp.get("sitemap") else (await _sitemaps_from_robots(ctx, site)) or [f"{site}/sitemap.xml"]
        urls: list[str] = []
        for sm in candidates[:3]:
            found, _ = await _sitemap_urls(ctx, sm, limit=400)
            urls.extend(found)
            if urls:
                break
        urls = [u for u in urls if urlsplit(u).path.count("/") >= 2 or len(urlsplit(u).path) > 20]
        take = urls[-int(comp.get("max_pages", 40)) :]
        stored = errors = 0
        async with session_factory()() as db:
            existing = {p.url: p for p in (await db.execute(select(SitePage).where(SitePage.tenant_id == ctx.tenant.id, SitePage.site == comp["key"]))).scalars()}
            for url in take:
                await ctx.beat()
                try:
                    res = await ctx.fetcher.get(url, respect_robots=True, use_cache=True)
                except FetchError:
                    errors += 1
                    continue
                if not res.content_type.startswith("text/html"):
                    continue
                meta = parse_page(res.text, url)
                row = existing.get(url) or SitePage(tenant_id=ctx.tenant.id, site=comp["key"], url=url)
                row.status_code, row.title, row.h1 = res.status, meta.title, (meta.h1[0] if meta.h1 else None)
                row.headline, row.meta_description, row.canonical = meta.headline, meta.meta_description, meta.canonical
                row.og, row.has_jsonld, row.word_count = meta.og, meta.has_jsonld, meta.word_count
                row.headings, row.first_paragraph, row.fetched_at = meta.headings, meta.first_paragraph, utcnow()
                if url not in existing:
                    db.add(row)
                stored += 1
            state[comp["key"]] = {"crawled_at": utcnow().isoformat(), "pages": stored, "errors": errors, "sitemaps": candidates[:3]}
            await kv_set(db, ctx.tenant.id, "seo.competitors", state)
            await db.commit()
        summary[comp["key"]] = {"pages": stored, "errors": errors}
        await ctx.log(f"{comp['name']}: {stored} page(s)")
    return summary


def topic_terms(texts: list[str], top: int = 25) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for t in texts:
        for tok in set(content_tokens(t)):
            if len(tok) >= 5:
                counts[tok] = counts.get(tok, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
