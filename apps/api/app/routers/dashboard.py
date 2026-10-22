"""Dashboard summary, activity feed and system health (plan §8.2). Every number comes from real rows."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.deps import Principal, current_principal, get_db
from app.models import Article, ArticleVersion, AuditLog, FeedItem, Job, KVState, ModelRun, Publication, ReviewAction, Tenant, Topic, User, WorkerHeartbeat
from app.providers.registry import get_provider
from app.queue.jobs import queue_stats
from app.serializers import audit_out, iso
from app.services.alerts import disk_usage
from app.services.tenant_settings import effective

router = APIRouter(tags=["dashboard"])

AGENTS = [
    ("A1", "discovery", "Discovery", ("discover",), ("discovery",)),
    ("A2", "research", "Research", ("research",), ("research",)),
    ("A3", "writer", "Writer", ("write",), ("writer",)),
    ("A4", "editor", "Editor", ("edit",), ("editor",)),
    ("A5", "seo", "SEO", ("seo", "crawl_inventory", "crawl_competitors"), ("seo",)),
    ("A6", "critic", "QA / Critic", ("qa", "eval"), ("critic",)),
    ("A8", "publisher", "Publisher", ("publish",), ()),
    ("A9", "distribution", "Distribution", ("social", "distribute"), ("linkedin",)),
]
IN_PROGRESS = ("queued", "researching", "drafting", "editing", "seo", "qa")


def _pct(values: list[int], p: float) -> int | None:
    if not values:
        return None
    values = sorted(values)
    k = min(len(values) - 1, max(0, int(round(p * (len(values) - 1)))))
    return values[k]


async def model_health(tenant_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    s = get_settings()
    provider = get_provider()
    h = await provider.health()
    cfg = effective(tenant_settings or {})
    wanted = sorted({a.get("model") for a in cfg["models"]["agents"].values() if a.get("model")} | ({s.model_embed} if s.model_embed else set()))
    have = set(h.models)

    def present(m: str) -> bool:
        return m in have or f"{m}:latest" in have or (m.endswith(":latest") and m[:-7] in have)

    missing = [m for m in wanted if not present(m)] if h.ok and provider.name != "mock" else []
    status = "ok" if h.ok and not missing else ("degraded" if h.ok else "down")
    return {
        "status": status,
        "provider": provider.name,
        "base_url": h.base_url,
        "models": h.models,
        "configured": wanted,
        "missing": missing,
        "latency_ms": h.latency_ms,
        "detail": h.detail
        or (f"Models not pulled: {', '.join(missing)} (run: ollama pull <model>)" if missing else None),
        "is_mock": provider.name == "mock",
    }


async def worker_health(db: AsyncSession) -> dict[str, Any]:
    rows = (await db.execute(select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen.desc()))).scalars().all()
    if not rows:
        return {"status": "down", "last_seen": None, "workers": 0, "detail": "No worker has reported in. Start: python -m app.worker"}
    newest = rows[0]
    age = (utcnow() - newest.last_seen).total_seconds()
    alive = [r for r in rows if (utcnow() - r.last_seen).total_seconds() < 90]
    status = "ok" if age < 90 else ("stale" if age < 600 else "down")
    return {
        "status": status,
        "last_seen": iso(newest.last_seen),
        "age_s": int(age),
        "workers": len(alive),
        "running": {k: v for r in alive for k, v in (r.info or {}).get("running", {}).items()},
    }


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    s = get_settings()
    checks: dict[str, Any] = {}
    started = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok", "latency_ms": int((time.perf_counter() - started) * 1000), "backend": "sqlite" if s.is_sqlite else "postgresql"}
    except Exception as exc:  # pragma: no cover - surfaced to operators
        checks["database"] = {"status": "down", "detail": str(exc)[:200]}
        return {"status": "down", "checks": checks, "version": "1.0.0", "time": iso(utcnow())}
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == s.tenant_default))).scalar_one_or_none()
    checks["model"] = await model_health(tenant.settings if tenant else None)
    checks["worker"] = await worker_health(db)
    du = disk_usage()
    checks["disk"] = {"status": "ok" if du["used_pct"] < s.disk_alert_pct else "degraded", **du}
    last = None
    if tenant:
        state = (await db.execute(select(KVState).where(KVState.tenant_id == tenant.id, KVState.key == "discovery.last_run"))).scalar_one_or_none()
        last = state.value if state else None
    age_h = None
    if last and last.get("at"):
        from datetime import datetime

        age_h = round((utcnow() - datetime.fromisoformat(last["at"])).total_seconds() / 3600, 1)
    checks["discovery"] = {
        "status": "ok" if age_h is not None and age_h < 6 else ("degraded" if age_h is not None else "unknown"),
        "last_run_at": last.get("at") if last else None,
        "age_h": age_h,
        "last_new_items": last.get("new_items") if last else None,
        "sources_ok": last.get("sources_ok") if last else None,
    }
    statuses = [c["status"] for c in checks.values()]
    overall = "ok" if all(x == "ok" for x in statuses) else ("down" if checks["database"]["status"] == "down" else "degraded")
    return {"status": overall, "checks": checks, "version": "1.0.0", "time": iso(utcnow())}


@router.get("/dashboard/summary")
async def summary(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    tid = principal.tenant_id
    now = utcnow()
    tz_day_start = now - timedelta(hours=24)
    week = now - timedelta(days=7)

    async def scalar(q) -> int:
        return int((await db.execute(q)).scalar_one() or 0)

    candidates_today = await scalar(
        select(func.count()).select_from(FeedItem).where(FeedItem.tenant_id == tid, FeedItem.fetched_at >= tz_day_start, FeedItem.is_cluster_head.is_(True))
    )
    drafts = await scalar(select(func.count()).select_from(Article).where(Article.tenant_id == tid, Article.state.in_(IN_PROGRESS)))
    awaiting = await scalar(select(func.count()).select_from(Article).where(Article.tenant_id == tid, Article.state == "in_review"))
    scheduled = await scalar(select(func.count()).select_from(Publication).where(Publication.tenant_id == tid, Publication.status == "scheduled"))
    published_7d = await scalar(
        select(func.count()).select_from(Publication).where(Publication.tenant_id == tid, Publication.status == "published", Publication.published_at >= week)
    )
    qstats = await queue_stats(db, tid)
    failed_jobs = qstats["failed"] + qstats["dead"]

    states = dict((await db.execute(select(Article.state, func.count()).where(Article.tenant_id == tid).group_by(Article.state))).all())

    promoted = await scalar(select(func.count()).select_from(Topic).where(Topic.tenant_id == tid, Topic.created_at >= week))
    drafted = await scalar(
        select(func.count(distinct(ArticleVersion.article_id)))
        .join(Article, Article.id == ArticleVersion.article_id)
        .where(Article.tenant_id == tid, ArticleVersion.stage.in_(("draft", "revised")), ArticleVersion.created_at >= week)
    )
    reached_review = await scalar(
        select(func.count(distinct(AuditLog.entity_id))).where(
            AuditLog.tenant_id == tid, AuditLog.action == "article.transition", AuditLog.created_at >= week
        ).where(AuditLog.detail["to"].as_string() == "in_review")
    )
    approved = await scalar(
        select(func.count(distinct(ReviewAction.article_id)))
        .join(Article, Article.id == ReviewAction.article_id)
        .where(Article.tenant_id == tid, ReviewAction.action == "approve", ReviewAction.created_at >= week)
    )
    discovered_7d = await scalar(
        select(func.count()).select_from(FeedItem).where(FeedItem.tenant_id == tid, FeedItem.fetched_at >= week, FeedItem.is_cluster_head.is_(True))
    )
    funnel = [
        {"stage": "discovered", "label": "Discovered", "count": discovered_7d},
        {"stage": "promoted", "label": "Promoted", "count": promoted},
        {"stage": "drafted", "label": "Drafted", "count": drafted},
        {"stage": "in_review", "label": "Reached review", "count": reached_review},
        {"stage": "approved", "label": "Approved", "count": approved},
        {"stage": "published", "label": "Published", "count": published_7d},
    ]

    # Daily series (UTC days)
    days = [(now - timedelta(days=i)).date() for i in range(6, -1, -1)]
    daily = {d.isoformat(): {"date": d.isoformat(), "discovered": 0, "drafted": 0, "published": 0} for d in days}
    for (fetched,) in (await db.execute(select(FeedItem.fetched_at).where(FeedItem.tenant_id == tid, FeedItem.fetched_at >= week, FeedItem.is_cluster_head.is_(True)))).all():
        key = fetched.date().isoformat()
        if key in daily:
            daily[key]["discovered"] += 1
    for (created,) in (
        await db.execute(
            select(ArticleVersion.created_at).join(Article, Article.id == ArticleVersion.article_id)
            .where(Article.tenant_id == tid, ArticleVersion.stage == "draft", ArticleVersion.created_at >= week)
        )
    ).all():
        key = created.date().isoformat()
        if key in daily:
            daily[key]["drafted"] += 1
    for (pub_at,) in (
        await db.execute(select(Publication.published_at).where(Publication.tenant_id == tid, Publication.status == "published", Publication.published_at >= week))
    ).all():
        key = pub_at.date().isoformat()
        if key in daily:
            daily[key]["published"] += 1

    # Agent health
    since = now - timedelta(hours=24)
    runs = (
        await db.execute(
            select(ModelRun.agent, ModelRun.latency_ms, ModelRun.error, ModelRun.created_at)
            .where(ModelRun.tenant_id == tid, ModelRun.created_at >= since)
            .order_by(ModelRun.created_at.desc())
            .limit(5000)
        )
    ).all()
    job_rows = (
        await db.execute(
            select(Job.type, Job.status, Job.started_at, Job.finished_at, Job.last_error, Job.created_at)
            .where(Job.tenant_id == tid, Job.created_at >= since)
            .order_by(Job.created_at.desc())
            .limit(5000)
        )
    ).all()
    by_agent_runs: dict[str, list] = defaultdict(list)
    for r in runs:
        by_agent_runs[r.agent.split(".")[0]].append(r)
    by_type_jobs: dict[str, list] = defaultdict(list)
    for j in job_rows:
        by_type_jobs[j.type].append(j)
    agents = []
    for code, key, label, job_types, run_keys in AGENTS:
        jl = [j for t in job_types for j in by_type_jobs.get(t, [])]
        rl = [r for k in run_keys for r in by_agent_runs.get(k, [])]
        durations = [int((j.finished_at - j.started_at).total_seconds() * 1000) for j in jl if j.finished_at and j.started_at and j.status == "done"]
        latencies = [r.latency_ms for r in rl if r.latency_ms is not None and not r.error]
        errors = [j for j in jl if j.status in ("failed", "dead")] + [r for r in rl if r.error]
        last_run = max([x.created_at for x in jl + rl], default=None)
        last_error = next((j.last_error for j in jl if j.last_error), None) or next((r.error for r in rl if r.error), None)
        agents.append(
            {
                "code": code,
                "agent": key,
                "label": label,
                "jobs_24h": len(jl),
                "model_calls_24h": len(rl),
                "errors_24h": len(errors),
                "p50_latency_ms": _pct(latencies or durations, 0.5),
                "p95_latency_ms": _pct(latencies or durations, 0.95),
                "avg_job_ms": int(sum(durations) / len(durations)) if durations else None,
                "last_run_at": iso(last_run),
                "last_error": (last_error or "")[:300] or None,
            }
        )
    tenant = await db.get(Tenant, tid)
    return {
        "cards": {
            "candidates_today": candidates_today,
            "drafts_in_progress": drafts,
            "awaiting_review": awaiting,
            "scheduled": scheduled,
            "published_7d": published_7d,
            "failed_jobs": failed_jobs,
        },
        "states": states,
        "funnel": funnel,
        "daily": list(daily.values()),
        "queue": qstats,
        "agents": agents,
        "model": await model_health(tenant.settings if tenant else None),
        "worker": await worker_health(db),
        "generated_at": iso(now),
    }


@router.get("/dashboard/activity")
async def activity(limit: int = Query(30, ge=1, le=200), principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(AuditLog).where(AuditLog.tenant_id == principal.tenant_id).order_by(AuditLog.id.desc()).limit(limit))
    ).scalars().all()
    user_ids = {r.actor_id for r in rows if r.actor_type == "user" and r.actor_id}
    emails: dict[str, str] = {}
    if user_ids:
        import uuid as _uuid

        ids = []
        for u in user_ids:
            try:
                ids.append(_uuid.UUID(u))
            except ValueError:
                pass
        for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars():
            emails[str(u.id)] = u.name or u.email
    titles: dict[str, str] = {}
    art_ids = []
    for r in rows:
        if r.entity == "article" and r.entity_id:
            try:
                import uuid as _uuid

                art_ids.append(_uuid.UUID(r.entity_id))
            except ValueError:
                pass
    if art_ids:
        for a in (await db.execute(select(Article.id, Article.title).where(Article.id.in_(art_ids)))).all():
            titles[str(a.id)] = a.title
    items = []
    for r in rows:
        out = audit_out(r, emails.get(r.actor_id or "") if r.actor_type == "user" else None)
        out["entity_label"] = titles.get(r.entity_id or "")
        items.append(out)
    return {"items": items}
