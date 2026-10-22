# ADR-001: Postgres table queue instead of Redis/Celery

- **Status:** Accepted
- **Date:** 2026-10-20
- **Deciders:** Rohit Jadhav (engine owner)

## Context

Every pipeline stage (discover, research, write, edit, SEO, QA, publish, distribute) runs as a background job. Jobs must survive restarts, retry with backoff, be visible when they fail, and never publish twice. Expected throughput is low — around ten jobs an hour, with long-running model jobs of several minutes each on CPU. The whole stack has to fit on one VPS next to a local LLM that needs most of the RAM.

## Decision

Use a `jobs` table in the same PostgreSQL database as the application state, claimed with `SELECT … FOR UPDATE SKIP LOCKED`.

- Claim: one atomic `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *`, ordered by `priority, available_at`.
- Retries: `attempts`/`max_attempts` on the row; backoff by pushing `available_at` forward (30 s, 2 min, 10 min).
- Crash recovery: a visibility timeout (10 min) re-queues `running` jobs whose lock is stale.
- Terminal failures move to `dead` with `last_error`, visible and retryable from the dashboard.
- A partial index on `(status, available_at, priority) WHERE status = 'queued'` keeps claims cheap.

## Consequences

**Positive**

- One less stateful service, container and failure mode; one backup covers state and queue.
- Job creation can be in the same transaction as the article state change, so state and queue never disagree.
- Jobs are plain rows: debuggable with SQL, displayable in the UI, auditable.
- Survives restarts without extra persistence configuration.

**Negative**

- Polling adds a small constant load (a claim query every few seconds per worker).
- Not suitable for thousands of jobs per second — irrelevant at this scale, but a ceiling to note.
- Scheduling and retry logic is ours to maintain and test.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Redis + Celery / RQ | Extra container and memory; persistence must be configured; job state not transactional with article state; harder to inspect. |
| RabbitMQ | Heavier still; no benefit at ~10 jobs/hour. |
| In-process asyncio tasks | Lost on restart; no retries or visibility. |
| Cron + scripts | No per-item retry, no visibility, no idempotency. |

Revisit if throughput exceeds ~100 jobs/minute or multiple worker hosts contend heavily on the claim query.
