#!/usr/bin/env python
"""Crawl the tenant's live site into the SEO inventory and print the audit (plan §3, §13.5).

    python scripts/crawl_site.py              # crawl + audit summary
    python scripts/crawl_site.py --csv fixes.csv
"""

from __future__ import annotations

import argparse
import asyncio
import json

import _bootstrap_path  # noqa: F401

from sqlalchemy import select

from app.agents.base import AgentContext, TenantSnapshot
from app.agents.crawl import crawl_inventory
from app.cli import ensure_tenant
from app.core.db import dispose_engine, session_factory
from app.models import SitePage
from app.providers.registry import get_provider
from app.services import site_audit
from app.services.fetcher import Fetcher
from app.services.integrations import kv_get


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=250)
    ap.add_argument("--csv", help="write the fix list to this CSV file")
    args = ap.parse_args()
    try:
        tenant = await ensure_tenant()
        async with Fetcher() as fetcher:
            ctx = AgentContext(tenant=TenantSnapshot.of(tenant), provider=get_provider(), fetcher=fetcher)
            print(json.dumps(await crawl_inventory(ctx, max_pages=args.max_pages), indent=2))
        async with session_factory()() as db:
            pages = list((await db.execute(select(SitePage).where(SitePage.tenant_id == tenant.id, SitePage.site == "own"))).scalars())
            state = await kv_get(db, tenant.id, "seo.inventory")
        report = site_audit.audit(pages, state)
        for f in report["findings"]:
            print(f"[{f['severity']:8}] {f['title']}: {f['evidence']}")
        if args.csv:
            site_url = TenantSnapshot.of(tenant).settings["brand"]["site_url"]
            rows = site_audit.fix_list(pages, site_url)
            with open(args.csv, "w", encoding="utf-8", newline="") as fh:
                fh.write(site_audit.fix_list_csv(rows))
            print(f"wrote {len(rows)} rows to {args.csv}")
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
