#!/usr/bin/env python
"""Prepare a demo environment from real sources only (no fake rows):

    python scripts/seed_demo.py --email you@example.com --password '…'

1. bootstrap (tenant, sources, eval cases) and create/update the admin
2. run one real discovery pass inline so the News Feed has today's items
3. optionally (--crawl) crawl the live site so the SEO audit shows live findings
"""

from __future__ import annotations

import argparse
import asyncio
import json

import _bootstrap_path  # noqa: F401

from app.agents.base import AgentContext, TenantSnapshot
from app.cli import bootstrap, create_user, ensure_tenant
from app.core.db import dispose_engine
from app.providers.registry import get_provider
from app.services.fetcher import Fetcher


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--crawl", action="store_true", help="also crawl the live site for the SEO audit")
    args = ap.parse_args()
    try:
        await bootstrap()
        tenant = await ensure_tenant()
        print(f"admin {args.email}: {await create_user(tenant, args.email, args.password, role='owner')}")
        async with Fetcher() as fetcher:
            ctx = AgentContext(tenant=TenantSnapshot.of(tenant), provider=get_provider(), fetcher=fetcher)
            from app.agents.discovery import run_discovery

            print(json.dumps(await run_discovery(ctx), indent=2))
            if args.crawl:
                from app.agents.crawl import crawl_inventory

                print(json.dumps(await crawl_inventory(ctx), indent=2))
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
