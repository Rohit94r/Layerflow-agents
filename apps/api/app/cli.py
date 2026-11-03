"""Operator CLI: `python -m app.cli <command>`.

  bootstrap        idempotent: tenant from config/tenants/ten.json, sources from config/sources/feeds.yaml,
                   admin from ADMIN_EMAIL/ADMIN_PASSWORD (if set), eval cases from evals/cases
  create-admin     --email --password [--name] [--role owner|editor|reviewer]
  seed-sources     add sources from feeds.yaml that are not present yet (matched by URL)
  reset-content    --yes  delete all fetched/generated content (feed, jobs, runs, articles, logs, sessions)
                   but keep the tenant, users, sources and eval cases
  run              --type discover|crawl_inventory|crawl_competitors|eval [--suite …]  run one job inline
  drain            process queued jobs until the queue is empty (no long-running worker)
  migrate          alembic upgrade head
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import dispose_engine, session_factory
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.models import EvalCase, Source, Tenant, User
from app.services.tenant_settings import deep_merge


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


async def ensure_tenant(slug: str | None = None) -> Tenant:
    s = get_settings()
    slug = slug or s.tenant_default
    path = s.config_dir / "tenants" / f"{slug}.json"
    seed = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"slug": slug, "name": slug.upper(), "settings": {}}
    async with session_factory()() as db:
        tenant = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(
                slug=slug,
                name=seed.get("name", slug),
                domain=seed.get("domain"),
                timezone=seed.get("timezone", "Asia/Kolkata"),
                settings=seed.get("settings", {}),
            )
            db.add(tenant)
            print(f"created tenant '{slug}'")
        else:
            # Fill keys added to the seed later without overwriting anything edited in Settings.
            tenant.settings = deep_merge(seed.get("settings", {}), tenant.settings or {})
        await db.commit()
        await db.refresh(tenant)
        return tenant


async def seed_sources(tenant: Tenant) -> int:
    path = get_settings().config_dir / "sources" / "feeds.yaml"
    if not path.exists():
        print("no feeds.yaml; skipping sources")
        return 0
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    added = 0
    async with session_factory()() as db:
        existing = set((await db.execute(select(Source.url).where(Source.tenant_id == tenant.id))).scalars())
        for src in data.get("sources", []):
            url = (src.get("url") or "").strip()
            if not url or url in existing:
                continue
            db.add(
                Source(
                    tenant_id=tenant.id,
                    kind=src.get("kind", "rss"),
                    name=src.get("name", url)[:200],
                    url=url,
                    weight=float(src.get("weight", 1.0)),
                    region=src.get("region"),
                    active=bool(src.get("active", True)),
                )
            )
            existing.add(url)
            added += 1
        await db.commit()
    return added


async def seed_eval_cases(tenant: Tenant) -> int:
    root = get_settings().evals_dir / "cases"
    if not root.exists():
        return 0
    n = 0
    async with session_factory()() as db:
        have = set((await db.execute(select(EvalCase.case_key).where(EvalCase.tenant_id == tenant.id))).scalars())
        for p in sorted(root.glob("*.json")):
            try:
                case = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if case.get("id") in have:
                continue
            db.add(EvalCase(tenant_id=tenant.id, case_key=case.get("id"), category=case.get("category", "brief"), input=case.get("input", {}), expected=case.get("expected"), label=case.get("label")))
            n += 1
        await db.commit()
    return n


# Content tables in delete order (children before parents). Configuration tables — tenants, users,
# sources, eval_cases — are deliberately left untouched.
CONTENT_TABLES = (
    "article_versions",
    "articles",
    "social_posts",
    "publications",
    "site_pages",
    "review_actions",
    "research_packs",
    "prompt_versions",
    "eval_runs",
    "model_runs",
    "job_events",
    "jobs",
    "feed_items",
    "topics",
    "audit_log",
    "sessions",
    "worker_heartbeats",
    "kv_state",
)


async def reset_content() -> dict[str, int]:
    """Delete all fetched/generated content. Stop the API and worker first."""
    from sqlalchemy import text

    from app.core.db import get_engine

    deleted: dict[str, int] = {}
    async with session_factory()() as db:
        for table in CONTENT_TABLES:
            count = (await db.execute(text(f'SELECT count(*) FROM "{table}"'))).scalar_one()
            await db.execute(text(f'DELETE FROM "{table}"'))
            deleted[table] = int(count)
        await db.commit()

    engine = get_engine()
    if engine.dialect.name == "sqlite":
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text("VACUUM"))
    return deleted


async def create_user(tenant: Tenant, email: str, password: str, *, name: str | None = None, role: str = "owner", update: bool = True) -> str:
    if len(password) < 10:
        raise SystemExit("Password must be at least 10 characters")
    async with session_factory()() as db:
        user = (await db.execute(select(User).where(User.tenant_id == tenant.id, func.lower(User.email) == email.lower()))).scalar_one_or_none()
        if user is None:
            db.add(User(tenant_id=tenant.id, email=email.lower(), name=name, role=role, password_hash=hash_password(password)))
            await db.commit()
            return "created"
        if update:
            user.password_hash = hash_password(password)
            user.role = role
            user.active = True
            if name:
                user.name = name
            await db.commit()
            return "updated"
        return "exists"


async def bootstrap() -> None:
    s = get_settings()
    tenant = await ensure_tenant()
    print(f"sources added: {await seed_sources(tenant)}")
    print(f"eval cases added: {await seed_eval_cases(tenant)}")
    if s.admin_email and s.admin_password:
        async with session_factory()() as db:
            count = (await db.execute(select(func.count()).select_from(User).where(User.tenant_id == tenant.id))).scalar_one()
        if count == 0:
            print(f"admin {s.admin_email}: {await create_user(tenant, s.admin_email, s.admin_password, role='owner', update=False)}")
        else:
            print("users exist; ADMIN_EMAIL not applied (use create-admin to reset)")
    else:
        print("ADMIN_EMAIL/ADMIN_PASSWORD not set; create one with: python -m app.cli create-admin --email … --password …")


async def run_inline(job_type: str, suite: str | None) -> None:
    from app.agents.base import AgentContext, TenantSnapshot
    from app.providers.registry import get_provider
    from app.services.fetcher import Fetcher

    tenant = await ensure_tenant()
    async with Fetcher() as fetcher:
        ctx = AgentContext(tenant=TenantSnapshot.of(tenant), provider=get_provider(), fetcher=fetcher)
        if job_type == "discover":
            from app.agents.discovery import run_discovery

            _print(await run_discovery(ctx))
        elif job_type == "crawl_inventory":
            from app.agents.crawl import crawl_inventory

            _print(await crawl_inventory(ctx))
        elif job_type == "crawl_competitors":
            from app.agents.crawl import crawl_competitors

            _print(await crawl_competitors(ctx))
        elif job_type == "eval":
            from app.agents.evals import run_eval

            _print(await run_eval(ctx, suite=suite or "deterministic"))
        else:
            raise SystemExit(f"unknown job type {job_type}")


async def drain() -> None:
    from app.worker import Worker

    w = Worker()
    try:
        n = await w.drain()
    finally:
        await w.fetcher.close()
    print(f"processed {n} job(s)")


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(cfg, "head")


def main(argv: list[str] | None = None) -> None:
    configure_logging(get_settings().log_level)
    p = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bootstrap")
    sub.add_parser("seed-sources")
    rc = sub.add_parser("reset-content")
    rc.add_argument("--yes", action="store_true", help="required: confirm the destructive reset")
    sub.add_parser("drain")
    sub.add_parser("migrate")
    ca = sub.add_parser("create-admin")
    ca.add_argument("--email", required=True)
    ca.add_argument("--password", required=True)
    ca.add_argument("--name")
    ca.add_argument("--role", default="owner", choices=["owner", "editor", "reviewer"])
    r = sub.add_parser("run")
    r.add_argument("--type", required=True, choices=["discover", "crawl_inventory", "crawl_competitors", "eval"])
    r.add_argument("--suite", choices=["deterministic", "critic", "pipeline"])
    args = p.parse_args(argv)

    async def _run() -> None:
        try:
            if args.cmd == "bootstrap":
                await bootstrap()
            elif args.cmd == "seed-sources":
                print(f"sources added: {await seed_sources(await ensure_tenant())}")
            elif args.cmd == "reset-content":
                if not args.yes:
                    raise SystemExit("refusing to delete content without --yes (stop the API and worker first)")
                deleted = await reset_content()
                print(json.dumps({k: v for k, v in deleted.items() if v}, indent=2))
                print("content cleared; tenant, users, sources and eval cases kept")
            elif args.cmd == "create-admin":
                tenant = await ensure_tenant()
                print(f"{args.email}: {await create_user(tenant, args.email, args.password, name=args.name, role=args.role)}")
            elif args.cmd == "run":
                await run_inline(args.type, args.suite)
            elif args.cmd == "drain":
                await drain()
        finally:
            await dispose_engine()

    if args.cmd == "migrate":
        migrate()
        return
    asyncio.run(_run())


if __name__ == "__main__":
    main(sys.argv[1:])
