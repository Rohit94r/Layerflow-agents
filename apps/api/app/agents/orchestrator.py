"""A0 Orchestrator — deterministic routing between agents (ADR-003). No LLM.

Rules: max 3 attempts per job (queue), max N revision loops (tenant quality.max_revisions, default 2),
stage transitions validated by the state machine, every transition audited."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import STAGE_ORDER, STAGE_STATE, IllegalTransition, assert_transition, next_stage, runnable_stages
from app.core.audit import audit
from app.core.db import utcnow
from app.models import Article, Job, Tenant
from app.queue.jobs import ACTIVE_STATUSES, enqueue
from app.services.tenant_settings import effective


async def active_job(db: AsyncSession, article_id: uuid.UUID) -> Job | None:
    return (
        await db.execute(
            select(Job)
            .where(Job.article_id == article_id, Job.status.in_(ACTIVE_STATUSES))
            .order_by(Job.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def transition(
    db: AsyncSession,
    article: Article,
    target: str,
    *,
    actor_type: str = "agent",
    actor_id: str | uuid.UUID | None = None,
    reason: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    current = article.state
    if current == target:
        return
    assert_transition(current, target)
    article.state = target
    article.updated_at = utcnow()
    if target not in ("failed", "needs_sources"):
        article.last_error = None
    audit(
        db,
        tenant_id=article.tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action="article.transition",
        entity="article",
        entity_id=article.id,
        detail={"from": current, "to": target, **({"reason": reason} if reason else {}), **(detail or {})},
    )


async def start_stage(
    db: AsyncSession,
    article: Article,
    stage: str,
    *,
    auto: bool,
    user_id: uuid.UUID | None = None,
    instruction: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Job:
    """Validate and enqueue a stage. `stage='auto'` runs research→qa from the start."""
    busy = await active_job(db, article.id)
    if busy is not None:
        raise IllegalTransition(article.state, f"{stage} (a {busy.type} job is already {busy.status})")
    if stage == "auto":
        stage, auto = "research", True
    if stage not in STAGE_ORDER:
        raise ValueError(f"Unknown stage {stage}")
    if stage not in runnable_stages(article.state):
        raise IllegalTransition(article.state, STAGE_STATE[stage])
    await transition(db, article, STAGE_STATE[stage], actor_type="user" if user_id else "agent", actor_id=user_id,
                     reason=f"run {stage}" + (" (auto)" if auto else ""))
    payload: dict[str, Any] = {"article_id": str(article.id), "auto": auto}
    if instruction:
        payload["instruction"] = instruction
    payload.update(extra or {})
    return await enqueue(db, tenant_id=article.tenant_id, type=stage, payload=payload, article_id=article.id, created_by=user_id)


async def _quality(db: AsyncSession, article: Article) -> dict[str, Any]:
    tenant = await db.get(Tenant, article.tenant_id)
    return effective(tenant.settings if tenant else {}).get("quality", {})


async def on_stage_success(db: AsyncSession, article: Article, stage: str, job: Job, result: dict[str, Any]) -> Job | None:
    auto = bool((job.payload or {}).get("auto"))
    if stage == "qa":
        verdict = result.get("verdict")
        if verdict == "pass":
            await transition(db, article, "in_review", reason="QA passed all gates")
            return None
        if verdict == "block":
            target = "needs_sources" if result.get("block_reason") == "grounding" else "failed"
            await transition(db, article, target, reason=result.get("summary") or "QA blocked")
            article.last_error = result.get("summary") or "QA blocked the article"
            return None
        # revise
        quality = await _quality(db, article)
        max_rev = int(quality.get("max_revisions", 2))
        if auto and article.revision_count < max_rev:
            article.revision_count += 1
            revise_stage = result.get("revise_stage") or "write"
            await transition(db, article, STAGE_STATE[revise_stage], reason=f"QA revise loop {article.revision_count}/{max_rev}")
            return await enqueue(
                db,
                tenant_id=article.tenant_id,
                type=revise_stage,
                payload={
                    "article_id": str(article.id),
                    "auto": True,
                    "instruction": result.get("revision_instruction") or "Fix the QA issues.",
                    "revision": article.revision_count,
                },
                article_id=article.id,
            )
        if auto:
            await transition(db, article, "failed", reason="QA gates not met after revision loops")
            article.last_error = (
                f"QA gates not met after {max_rev} revision(s): " + (result.get("summary") or "see QA report")
            )[:2000]
        return None
    if auto:
        nxt = next_stage(stage)
        if nxt:
            await transition(db, article, STAGE_STATE[nxt], reason=f"{stage} done (auto)")
            return await enqueue(
                db, tenant_id=article.tenant_id, type=nxt, payload={"article_id": str(article.id), "auto": True}, article_id=article.id
            )
    return None


async def on_stage_blocked(db: AsyncSession, article: Article, reason: str) -> None:
    if article.state != "needs_sources":
        try:
            await transition(db, article, "needs_sources", reason=reason)
        except IllegalTransition:
            # e.g. the writer found no usable pack: route back through research.
            await transition(db, article, "failed", reason=reason)
    article.last_error = reason[:2000]


async def on_stage_failed(db: AsyncSession, article: Article, stage: str, error: str) -> None:
    if article.state != "failed":
        try:
            await transition(db, article, "failed", reason=f"{stage} failed")
        except IllegalTransition:
            article.state = "failed"
    article.last_error = f"{stage}: {error}"[:2000]
