"""Worker process: `python -m app.worker`.

Two lanes so a 20-minute CPU generation never blocks a publish: the model lane runs MODEL_CONCURRENCY jobs
(default 1), the io lane runs fetch/publish jobs in parallel. Housekeeping: heartbeat, visibility-timeout
recovery, scheduler tick, discovery cadence, model/disk health alerts, daily retention."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.agents import orchestrator
from app.agents.base import AgentContext, InsufficientEvidence, TenantSnapshot
from app.agents.state import STAGE_ORDER, IllegalTransition
from app.core.audit import audit
from app.core.config import get_settings
from app.core.db import session_factory, utcnow
from app.core.logging import configure_logging, job_id_var
from app.models import Article, Job, KVState, Tenant, WorkerHeartbeat
from app.providers.registry import GuardedProvider, get_provider
from app.queue import jobs as q
from app.services import alerts
from app.services.fetcher import Fetcher
from app.services.tenant_settings import effective

log = logging.getLogger("app.worker")


async def _handle(ctx: AgentContext, job: Job) -> dict[str, Any]:
    p = job.payload or {}
    t = job.type
    if t == "discover":
        from app.agents.discovery import run_discovery

        return await run_discovery(ctx, source_id=p.get("source_id"))
    if t == "research":
        from app.agents.research import run_research

        return await run_research(ctx, job.article_id)
    if t == "write":
        from app.agents.writer import run_writer

        return await run_writer(ctx, job.article_id, instruction=p.get("instruction"), revision=int(p.get("revision", 0)))
    if t == "edit":
        from app.agents.editor import run_editor

        return await run_editor(ctx, job.article_id, instruction=p.get("instruction"))
    if t == "seo":
        from app.agents.seo import run_seo

        return await run_seo(ctx, job.article_id, instruction=p.get("instruction"))
    if t == "qa":
        from app.agents.critic import run_critic

        return await run_critic(ctx, job.article_id)
    if t == "publish":
        from app.agents.publisher import run_publish

        return await run_publish(ctx, uuid.UUID(p["publication_id"]))
    if t == "social":
        from app.agents.distribution import run_social_generate

        return await run_social_generate(ctx, uuid.UUID(p["article_id"]))
    if t == "distribute":
        from app.agents.distribution import run_distribute

        return await run_distribute(ctx, uuid.UUID(p["social_post_id"]))
    if t == "crawl_inventory":
        from app.agents.crawl import crawl_inventory

        return await crawl_inventory(ctx, max_pages=int(p.get("max_pages", 250)))
    if t == "crawl_competitors":
        from app.agents.crawl import crawl_competitors

        return await crawl_competitors(ctx)
    if t == "eval":
        from app.agents.evals import run_eval

        return await run_eval(ctx, suite=p.get("suite", "critic"), case_ids=p.get("case_ids"))
    if t == "maintenance":
        from app.agents.maintenance import run_maintenance

        return await run_maintenance(p, ctx.tenant.id)
    raise q.PermanentError(f"No handler for job type {t}")


class Worker:
    def __init__(self, worker_id: str | None = None, provider: GuardedProvider | None = None, fetcher: Fetcher | None = None) -> None:
        self.s = get_settings()
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.provider = provider or get_provider()
        self.fetcher = fetcher or Fetcher(self.s)
        self.stopping = asyncio.Event()
        self.running: dict[uuid.UUID, str] = {}
        self.consecutive_failures = 0
        self.model_ok: bool | None = None

    # ---------- job lifecycle ----------
    async def process(self, job: Job) -> str:
        job_id_var.set(str(job.id))
        async with session_factory()() as db:
            tenant = await db.get(Tenant, job.tenant_id)
            snapshot = TenantSnapshot.of(tenant)
        ctx = AgentContext(
            tenant=snapshot, provider=self.provider, fetcher=self.fetcher, job_id=job.id, article_id=job.article_id, worker_id=self.worker_id
        )
        self.running[job.id] = job.type
        log.info("job start", extra={"job_type": job.type, "tenant": snapshot.slug})
        await ctx.log(f"{job.type} started (attempt {job.attempts}/{job.max_attempts}) on {self.worker_id.split(':')[0]}")
        beat_task = asyncio.create_task(self._job_heartbeat(job.id))
        try:
            result = await _handle(ctx, job)
        except InsufficientEvidence as exc:
            await self._blocked(job, str(exc))
            await ctx.log(str(exc), level="warn")
            return "blocked"
        except q.JobError as exc:
            return await self._failed(ctx, job, str(exc), retryable=exc.retryable, retry_after=exc.retry_after_s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # unexpected bug: retry with backoff, keep the traceback in logs
            log.exception("job crashed")
            return await self._failed(ctx, job, f"{exc.__class__.__name__}: {exc}", retryable=True, retry_after=None)
        finally:
            beat_task.cancel()
            self.running.pop(job.id, None)
        await self._succeeded(job, result or {})
        await ctx.log(f"{job.type} finished")
        self.consecutive_failures = 0
        return "done"

    async def _job_heartbeat(self, job_id: uuid.UUID) -> None:
        try:
            while True:
                await asyncio.sleep(self.s.worker_heartbeat_s)
                await q.heartbeat(job_id, self.worker_id)
        except asyncio.CancelledError:
            return

    async def _succeeded(self, job: Job, result: dict[str, Any]) -> None:
        async with session_factory()() as db:
            row = await db.get(Job, job.id)
            if row.type in STAGE_ORDER and row.article_id:
                article = await db.get(Article, row.article_id)
                if article is not None:
                    try:
                        nxt = await orchestrator.on_stage_success(db, article, row.type, row, result)
                    except IllegalTransition as exc:
                        # The article moved on while the job ran (e.g. archived by a user): keep its state.
                        log.warning("skip routing after %s: %s", row.type, exc)
                        nxt = None
                    if nxt is not None:
                        result = {**result, "next_job": str(nxt.id)}
            audit(db, tenant_id=row.tenant_id, actor_type="agent", actor_id=row.type, action="job.done", entity="job", entity_id=row.id,
                  detail={"type": row.type, "article_id": str(row.article_id) if row.article_id else None})
            await q.complete(db, row, result)

    async def _blocked(self, job: Job, reason: str) -> None:
        async with session_factory()() as db:
            row = await db.get(Job, job.id)
            if row.article_id:
                article = await db.get(Article, row.article_id)
                if article is not None:
                    await orchestrator.on_stage_blocked(db, article, reason)
            await q.complete(db, row, {"outcome": "needs_sources", "reason": reason})

    async def _failed(self, ctx: AgentContext, job: Job, error: str, *, retryable: bool, retry_after: float | None) -> str:
        async with session_factory()() as db:
            row = await db.get(Job, job.id)
            status = await q.fail(db, row, error, retryable=retryable, retry_after_s=retry_after)
            if status in ("failed", "dead"):
                if row.type in STAGE_ORDER and row.article_id:
                    article = await db.get(Article, row.article_id)
                    if article is not None:
                        await orchestrator.on_stage_failed(db, article, row.type, error)
                audit(db, tenant_id=row.tenant_id, actor_type="agent", actor_id=row.type, action="job.failed", entity="job",
                      entity_id=row.id, detail={"error": error[:500], "status": status})
                await db.commit()
        if status in ("failed", "dead") and job.type == "publish":
            from app.agents.publisher import on_publish_failed

            await on_publish_failed(uuid.UUID(job.payload["publication_id"]), error)
            await alerts.send("publish_failed", f"Publish failed for publication {job.payload['publication_id']}: {error[:200]}")
        level = "warn" if status == "queued" else "error"
        await ctx.log(
            f"{job.type} failed: {error[:300]}" + (" — will retry" if status == "queued" else f" — {status}"), level=level
        )
        self.consecutive_failures += 1
        if self.consecutive_failures >= 3:
            await alerts.send("job_failures", f"{self.consecutive_failures} consecutive job failures; last: {job.type}: {error[:200]}")
        return status

    async def run_once(self, types: frozenset[str] | None = None) -> str | None:
        types = types or q.JOB_TYPES
        async with session_factory()() as db:
            job = await q.claim(db, self.worker_id, types)
        if job is None:
            return None
        return await self.process(job)

    async def drain(self, types: frozenset[str] | None = None, max_jobs: int = 200) -> int:
        """Process jobs until the queue is empty (tests / CLI)."""
        n = 0
        while n < max_jobs and await self.run_once(types) is not None:
            n += 1
        return n

    # ---------- loops ----------
    async def lane(self, name: str, types: frozenset[str]) -> None:
        while not self.stopping.is_set():
            try:
                outcome = await self.run_once(types)
            except Exception:
                log.exception("lane %s error", name)
                outcome = None
            if outcome is None:
                try:
                    await asyncio.wait_for(self.stopping.wait(), timeout=self.s.worker_poll_interval_s)
                except TimeoutError:
                    pass

    async def housekeeping(self) -> None:
        last: dict[str, datetime] = {}

        def due(key: str, every: timedelta) -> bool:
            now = utcnow()
            if key not in last or now - last[key] >= every:
                last[key] = now
                return True
            return False

        started = utcnow()
        while not self.stopping.is_set():
            try:
                await self._beat(started)
                if due("stale", timedelta(seconds=60)):
                    async with session_factory()() as db:
                        stale = await q.requeue_stale(db, self.s.worker_visibility_timeout_s)
                        if stale:
                            log.warning("re-queued %d stale job(s)", len(stale))
                if due("scheduler", timedelta(seconds=self.s.scheduler_tick_s)):
                    from app.agents.scheduler import tick

                    async with session_factory()() as db:
                        await tick(db)
                if due("discovery", timedelta(minutes=5)):
                    await self._discovery_cadence()
                if due("model", timedelta(minutes=5)):
                    await self._check_model()
                if due("disk", timedelta(hours=1)):
                    du = alerts.disk_usage()
                    if du["used_pct"] >= self.s.disk_alert_pct:
                        await alerts.send("disk", f"Disk {du['used_pct']}% used ({du['free_gb']} GB free)")
                if due("retention", timedelta(hours=24)) and utcnow() - started > timedelta(minutes=10):
                    from app.agents.maintenance import apply_retention

                    log.info("retention: %s", await apply_retention())
            except Exception:
                log.exception("housekeeping error")
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=10)
            except TimeoutError:
                pass

    async def _beat(self, started: datetime) -> None:
        async with session_factory()() as db:
            row = await db.get(WorkerHeartbeat, self.worker_id)
            info = {"running": {str(k): v for k, v in self.running.items()}, "provider": self.provider.name, "pid": os.getpid()}
            if row is None:
                db.add(WorkerHeartbeat(worker_id=self.worker_id, started_at=started, last_seen=utcnow(), info=info))
            else:
                row.last_seen = utcnow()
                row.info = info
            await db.commit()

    async def _discovery_cadence(self) -> None:
        async with session_factory()() as db:
            for tenant in (await db.execute(select(Tenant))).scalars():
                dcfg = effective(tenant.settings).get("discovery", {})
                interval = int(dcfg.get("interval_minutes", 30))
                if interval <= 0:
                    continue
                state = (
                    await db.execute(select(KVState).where(KVState.tenant_id == tenant.id, KVState.key == "discovery.last_run"))
                ).scalar_one_or_none()
                last_at = datetime.fromisoformat(state.value["at"]) if state and state.value.get("at") else None
                if last_at is None or utcnow() - last_at >= timedelta(minutes=interval):
                    await q.enqueue(db, tenant_id=tenant.id, type="discover", payload={"scheduled": True}, dedupe_key="discover:all")
            await db.commit()

    async def _check_model(self) -> None:
        h = await self.provider.health()
        if self.model_ok is not False and not h.ok:
            await alerts.send("model_down", f"Model endpoint down: {h.detail or h.base_url}")
        self.model_ok = h.ok

    async def release_running(self) -> None:
        async with session_factory()() as db:
            await db.execute(
                update(Job)
                .where(Job.locked_by == self.worker_id, Job.status == "running")
                .values(status="queued", locked_by=None, locked_at=None, available_at=utcnow(), last_error="Worker shut down; re-queued")
            )
            await db.commit()

    async def run_forever(self) -> None:
        log.info("worker %s starting (provider=%s)", self.worker_id, self.provider.name)
        tasks = [asyncio.create_task(self.housekeeping())]
        for i in range(max(1, self.s.model_concurrency)):
            tasks.append(asyncio.create_task(self.lane(f"model-{i}", q.MODEL_LANE)))
        for i in range(max(1, self.s.io_concurrency)):
            tasks.append(asyncio.create_task(self.lane(f"io-{i}", q.IO_LANE)))
        await self.stopping.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.release_running()
        await self.fetcher.close()
        log.info("worker stopped")


async def main() -> None:
    s = get_settings()
    configure_logging(s.log_level)
    worker = Worker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stopping.set)
        except (NotImplementedError, RuntimeError):  # Windows
            signal.signal(sig, lambda *_: worker.stopping.set())
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
