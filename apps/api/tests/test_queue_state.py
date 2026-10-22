"""Queue + state machine (plan §7.2, §16): claim, retry/backoff, dead after max attempts, visibility-timeout
recovery (kill worker mid-job), dedupe, illegal transitions."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.agents.state import IllegalTransition, assert_transition, can_transition, runnable_stages
from app.core.db import session_factory, utcnow
from app.models import Job
from app.queue import jobs as q


async def test_enqueue_claim_complete(tenant):
    async with session_factory()() as db:
        j = await q.enqueue(db, tenant_id=tenant.id, type="discover", payload={}, dedupe_key="discover:all")
        dup = await q.enqueue(db, tenant_id=tenant.id, type="discover", payload={}, dedupe_key="discover:all")
        await db.commit()
        assert dup.id == j.id  # double click → one job
    async with session_factory()() as db:
        claimed = await q.claim(db, "w1", q.IO_LANE)
        assert claimed is not None and claimed.status == "running" and claimed.attempts == 1
        again = await q.claim(db, "w2", q.IO_LANE)
        assert again is None  # never claimed twice
        await q.complete(db, claimed, {"ok": True})
    async with session_factory()() as db:
        assert (await db.get(Job, j.id)).status == "done"


async def test_retry_backoff_then_dead(tenant):
    async with session_factory()() as db:
        j = await q.enqueue(db, tenant_id=tenant.id, type="discover", payload={}, max_attempts=2)
        await db.commit()
    async with session_factory()() as db:
        c = await q.claim(db, "w", q.IO_LANE)
        status = await q.fail(db, c, "timeout")
        assert status == "queued" and c.available_at > utcnow() + timedelta(seconds=20)
        c.available_at = utcnow() - timedelta(seconds=1)
        await db.commit()
    async with session_factory()() as db:
        c = await q.claim(db, "w", q.IO_LANE)
        assert c.attempts == 2
        assert await q.fail(db, c, "timeout again") == "dead"
    async with session_factory()() as db:
        row = await db.get(Job, j.id)
        assert row.status == "dead" and row.last_error == "timeout again"
        await q.retry(db, row)
        await db.commit()
        assert row.status == "queued" and row.attempts == 0


async def test_permanent_failure_not_retried(tenant):
    async with session_factory()() as db:
        await q.enqueue(db, tenant_id=tenant.id, type="publish", payload={"publication_id": "x"})
        await db.commit()
    async with session_factory()() as db:
        c = await q.claim(db, "w", q.IO_LANE)
        assert await q.fail(db, c, "HTTP 403", retryable=False) == "failed"


async def test_worker_killed_mid_job_is_requeued(tenant):
    async with session_factory()() as db:
        j = await q.enqueue(db, tenant_id=tenant.id, type="research", payload={}, article_id=None)
        await db.commit()
    async with session_factory()() as db:
        c = await q.claim(db, "dead-worker", q.MODEL_LANE)
        c.locked_at = utcnow() - timedelta(minutes=30)  # worker vanished; no heartbeats
        await db.commit()
    async with session_factory()() as db:
        stale = await q.requeue_stale(db, visibility_timeout_s=600)
        assert [s.id for s in stale] == [j.id]
    async with session_factory()() as db:
        row = await db.get(Job, j.id)
        assert row.status == "queued" and "visibility timeout" in row.last_error
        again = await q.claim(db, "w2", q.MODEL_LANE)
        assert again.id == j.id and again.attempts == 2


def test_state_machine_legal_and_illegal():
    assert can_transition("queued", "researching")
    assert can_transition("qa", "drafting")  # revise loop
    assert can_transition("in_review", "approved")
    for cur, nxt in [("queued", "published"), ("drafting", "approved"), ("archived", "published"), ("scheduled", "drafting"), ("in_review", "published")]:
        with pytest.raises(IllegalTransition):
            assert_transition(cur, nxt)
    assert runnable_stages("queued") == ["research"]
    assert runnable_stages("in_review", busy=True) == []
    assert runnable_stages("scheduled") == []
    assert "write" in runnable_stages("failed")
