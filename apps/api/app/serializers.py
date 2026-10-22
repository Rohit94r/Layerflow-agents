"""Wire format for every API response. The dashboard's TypeScript types (apps/web/lib/types.ts) mirror this file."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models import (
    Article,
    ArticleVersion,
    AuditLog,
    EvalRun,
    FeedItem,
    Job,
    JobEvent,
    Publication,
    ResearchPack,
    ReviewAction,
    SitePage,
    SocialPost,
    Source,
    Tenant,
    Topic,
    User,
)
from app.services.playbooks import PLAYBOOKS


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def sid(value: Any) -> str | None:
    return str(value) if value is not None else None


def user_out(u: User) -> dict[str, Any]:
    return {"id": str(u.id), "email": u.email, "name": u.name or u.email.split("@")[0], "role": u.role}


def tenant_out(t: Tenant) -> dict[str, Any]:
    brand = (t.settings or {}).get("brand", {})
    return {
        "id": str(t.id),
        "slug": t.slug,
        "name": t.name,
        "domain": t.domain,
        "timezone": t.timezone,
        "site_url": brand.get("site_url"),
    }


def job_out(j: Job) -> dict[str, Any]:
    payload = {k: v for k, v in (j.payload or {}).items() if k not in {"dedupe_key"}}
    return {
        "id": str(j.id),
        "type": j.type,
        "status": j.status,
        "article_id": sid(j.article_id),
        "priority": j.priority,
        "attempts": j.attempts,
        "max_attempts": j.max_attempts,
        "available_at": iso(j.available_at),
        "locked_at": iso(j.locked_at),
        "locked_by": j.locked_by,
        "last_error": j.last_error,
        "payload": payload,
        "result": j.result,
        "created_at": iso(j.created_at),
        "started_at": iso(j.started_at),
        "finished_at": iso(j.finished_at),
        "duration_ms": int((j.finished_at - j.started_at).total_seconds() * 1000)
        if j.finished_at and j.started_at
        else None,
    }


def job_event_out(e: JobEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "job_id": sid(e.job_id),
        "article_id": sid(e.article_id),
        "level": e.level,
        "message": e.message,
        "data": e.data,
        "created_at": iso(e.created_at),
    }


def source_out(s: Source, items_7d: int | None = None) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "kind": s.kind,
        "name": s.name,
        "url": s.url,
        "weight": s.weight,
        "region": s.region,
        "active": s.active,
        "last_fetched_at": iso(s.last_fetched_at),
        "last_error": s.last_error,
        "consecutive_failures": s.consecutive_failures,
        "last_item_count": s.last_item_count,
        "last_latency_ms": s.last_latency_ms,
        "items_7d": items_7d,
        "created_at": iso(s.created_at),
    }


def feed_item_out(
    f: FeedItem, *, cluster_size: int | None = None, topic_id: Any = None, article_id: Any = None
) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "title": f.title,
        "url": f.url,
        "canonical_url": f.canonical_url,
        "publisher": f.publisher or (f.source.name if f.source else None),
        "summary": f.summary,
        "published_at": iso(f.published_at),
        "fetched_at": iso(f.fetched_at),
        "source": {"id": str(f.source.id), "name": f.source.name, "kind": f.source.kind} if f.source else None,
        "lang": f.lang,
        "entities": f.entities or [],
        "region": f.region,
        "score": round(f.score or 0.0, 4),
        "score_breakdown": f.score_breakdown or {},
        "suggested_category": f.suggested_category,
        "category_reason": f.category_reason,
        "why_it_matters": f.why_it_matters,
        "dedupe_cluster_id": sid(f.dedupe_cluster_id),
        "is_cluster_head": f.is_cluster_head,
        "cluster_size": cluster_size,
        "status": f.status,
        "ignored_reason": f.ignored_reason,
        "topic_id": sid(topic_id),
        "article_id": sid(article_id),
    }


def topic_out(t: Topic) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "feed_item_id": sid(t.feed_item_id),
        "category": t.category,
        "title": t.title,
        "angle": t.angle,
        "region": t.region,
        "notes": t.notes,
        "links": t.links or [],
        "status": t.status,
        "created_at": iso(t.created_at),
    }


def article_summary(a: Article, active_job: Job | None = None) -> dict[str, Any]:
    pb = PLAYBOOKS.get(a.category)
    return {
        "id": str(a.id),
        "title": a.title or (a.topic.title if a.topic else "Untitled"),
        "category": a.category,
        "category_label": pb.label if pb else a.category,
        "state": a.state,
        "slug": a.slug,
        "quality_score": a.quality_score,
        "revision_count": a.revision_count,
        "last_error": a.last_error,
        "published_url": a.published_url,
        "topic": {
            "id": str(a.topic.id),
            "title": a.topic.title,
            "angle": a.topic.angle,
            "region": a.topic.region,
            "feed_item_id": sid(a.topic.feed_item_id),
        }
        if a.topic
        else None,
        "active_job": {"id": str(active_job.id), "type": active_job.type, "status": active_job.status}
        if active_job
        else None,
        "created_at": iso(a.created_at),
        "updated_at": iso(a.updated_at),
    }


def version_out(v: ArticleVersion, *, include_payload: bool = True) -> dict[str, Any]:
    out = {
        "id": str(v.id),
        "stage": v.stage,
        "prompt_version": v.prompt_version,
        "model_run_id": sid(v.model_run_id),
        "note": v.note,
        "created_by": sid(v.created_by),
        "created_at": iso(v.created_at),
        "word_count": ((v.payload or {}).get("article") or {}).get("word_count"),
    }
    if include_payload:
        out["payload"] = v.payload
    return out


def research_out(r: ResearchPack) -> dict[str, Any]:
    payload = dict(r.payload or {})
    # Source excerpts are kept for grounding checks but are too heavy for the UI list.
    payload["sources"] = [{k: v for k, v in s.items() if k != "excerpt"} for s in payload.get("sources", [])]
    return {
        "id": str(r.id),
        "status": r.status,
        "source_count": r.source_count,
        "created_at": iso(r.created_at),
        "payload": payload,
    }


def publication_out(p: Publication, article: Article | None = None) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "article_id": str(p.article_id),
        "article": {
            "id": str(article.id),
            "title": article.title,
            "category": article.category,
            "slug": article.slug,
            "state": article.state,
        }
        if article
        else None,
        "version_id": sid(p.version_id),
        "target": p.target,
        "status": p.status,
        "scheduled_at": iso(p.scheduled_at),
        "published_at": iso(p.published_at),
        "remote_id": p.remote_id,
        "live_url": p.live_url,
        "idempotency_key": p.idempotency_key,
        "content_hash": p.content_hash,
        "last_error": p.last_error,
        "has_artifact": bool(p.artifact_path),
        "warnings": p.warnings or [],
        "late": p.late,
        "created_at": iso(p.created_at),
    }


def social_out(s: SocialPost, article: Article | None = None) -> dict[str, Any]:
    from app.services.social_rules import check_post

    return {
        "id": str(s.id),
        "article_id": str(s.article_id),
        "article": {
            "id": str(article.id),
            "title": article.title,
            "category": article.category,
            "published_url": article.published_url,
            "state": article.state,
        }
        if article
        else None,
        "platform": s.platform,
        "text": s.text,
        "hook": s.hook,
        "cta": s.cta,
        "link": s.link,
        "hashtags": s.hashtags or [],
        "image_url": s.image_url,
        "image_spec": s.image_spec,
        "status": s.status,
        "remote_urn": s.remote_urn,
        "published_at": iso(s.published_at),
        "last_error": s.last_error,
        "char_count": len(s.text or ""),
        "issues": check_post(s.text or "", s.hashtags or []),
        "created_at": iso(s.created_at),
        "updated_at": iso(s.updated_at),
    }


def review_action_out(r: ReviewAction, user: User | None = None) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "action": r.action,
        "reason": r.reason,
        "user": user_out(user) if user else None,
        "created_at": iso(r.created_at),
    }


def audit_out(a: AuditLog, actor_label: str | None = None) -> dict[str, Any]:
    return {
        "id": a.id,
        "actor_type": a.actor_type,
        "actor_id": a.actor_id,
        "actor_label": actor_label or (a.actor_id if a.actor_type != "user" else "user"),
        "action": a.action,
        "entity": a.entity,
        "entity_id": a.entity_id,
        "detail": a.detail,
        "created_at": iso(a.created_at),
    }


def site_page_out(p: SitePage) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "site": p.site,
        "url": p.url,
        "status_code": p.status_code,
        "title": p.title,
        "h1": p.h1,
        "headline": p.headline,
        "meta_description": p.meta_description,
        "canonical": p.canonical,
        "og_count": len(p.og or {}),
        "has_jsonld": p.has_jsonld,
        "word_count": p.word_count,
        "headings": (p.headings or [])[:12],
        "fetched_at": iso(p.fetched_at),
    }


def eval_run_out(r: EvalRun, *, include_details: bool = False) -> dict[str, Any]:
    out = {
        "id": str(r.id),
        "agent": r.agent,
        "model": r.model,
        "scores": r.scores,
        "passed": r.passed,
        "total": r.total,
        "created_at": iso(r.created_at),
    }
    if include_details:
        out["details"] = r.details
    return out
