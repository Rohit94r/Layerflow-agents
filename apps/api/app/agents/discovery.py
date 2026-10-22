"""A1 Discovery — free-source news finding, normalisation, three-layer dedupe, transparent scoring,
rules-first category routing, small-model enrichment for the top candidates."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.base import AgentContext, structured
from app.core.audit import audit
from app.core.db import session_factory, utcnow
from app.models import FeedItem, KVState, Source
from app.queue.jobs import JobError
from app.services import dedupe, scoring
from app.services.entities import extract_entities, tag_region
from app.services.feeds import FeedParseError, RawItem, parse_ir_html, parse_source
from app.services.fetcher import FetchError
from app.services.prompts import compose_system, versions_tag
from app.services.router_rules import route_category
from app.services.text import looks_english, truncate_words

log = logging.getLogger(__name__)
CategoryLit = Literal["brief", "thinking", "room", "playbook", "decisions", "deep_dive"]


class EntityOut(BaseModel):
    name: str = Field(max_length=120)
    type: Literal["company", "person", "country", "sector"]


class Classification(BaseModel):
    category: CategoryLit
    confidence: float = Field(ge=0, le=1)
    why_it_matters: str = Field(min_length=10, max_length=180)
    entities: list[EntityOut] = Field(default_factory=list, max_length=8)


async def _fetch_source(ctx: AgentContext, src: Source) -> tuple[Source, list[RawItem], str | None, int]:
    started = time.perf_counter()
    try:
        res = await ctx.fetcher.get(src.url, respect_robots=False, use_cache=False)
        items = parse_source(src.kind, res.text) if not (src.kind == "ir" and res.content_type == "text/html") else parse_ir_html(res.text, src.url)
        return src, items, None, int((time.perf_counter() - started) * 1000)
    except (FetchError, FeedParseError) as exc:
        return src, [], str(exc), int((time.perf_counter() - started) * 1000)
    except Exception as exc:  # malformed feeds must never crash the run
        log.exception("source %s crashed the parser", src.name)
        return src, [], f"Parser error: {exc.__class__.__name__}", int((time.perf_counter() - started) * 1000)


async def run_discovery(ctx: AgentContext, *, source_id: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    settings = ctx.tenant.settings
    dcfg = settings.get("discovery", {})
    weights = settings.get("scoring", {})
    watchlist = settings.get("watchlist", {})
    avoid = [t.lower() for t in (settings.get("avoid", {}).get("topics", []) + settings.get("avoid", {}).get("companies", []))]
    lookback_h = int(dcfg.get("lookback_hours", 24))
    max_items = int(dcfg.get("max_items", 300))
    now = utcnow()

    async with session_factory()() as db:
        q = select(Source).where(Source.tenant_id == ctx.tenant.id)
        q = q.where(Source.id == uuid.UUID(source_id)) if source_id else q.where(Source.active.is_(True))
        sources = list((await db.execute(q)).scalars().all())
    if not sources:
        raise JobError("No active sources configured. Add sources in Settings → Sources.")
    await ctx.log(f"Fetching {len(sources)} source(s)")

    results = await asyncio.gather(*(_fetch_source(ctx, s) for s in sources))
    await ctx.beat()

    raw: list[tuple[Source, RawItem]] = []
    health: list[dict[str, Any]] = []
    for src, items, err, latency in results:
        health.append({"id": src.id, "error": err, "count": len(items), "latency": latency})
        for it in items:
            raw.append((src, it))
    ok_sources = sum(1 for h in health if not h["error"])
    await ctx.log(f"{ok_sources}/{len(sources)} sources responded; {len(raw)} raw items")

    # ---- normalise + filter ----
    cutoff = now - timedelta(hours=max(lookback_h * 2, 48))
    seen_urls: set[str] = set()
    candidates: list[dict[str, Any]] = []
    stats = {"raw": len(raw), "too_old": 0, "non_english": 0, "avoided": 0, "dup_url": 0, "dup_title": 0, "clustered": 0}
    for src, it in raw:
        canon = it.canonical_url
        if canon in seen_urls:
            stats["dup_url"] += 1
            continue
        seen_urls.add(canon)
        if it.published_at and it.published_at < cutoff:
            stats["too_old"] += 1
            continue
        text = f"{it.title} {it.summary}"
        if (it.lang and not it.lang.lower().startswith("en")) or not looks_english(text):
            stats["non_english"] += 1
            continue
        if any(a and a in text.lower() for a in avoid):
            stats["avoided"] += 1
            continue
        ents = extract_entities(it.title, it.summary, watchlist)
        region = tag_region(it.title, it.summary, default=src.region, entities=ents)
        category, reason = route_category(
            it.title, it.summary, source_kind=src.kind, has_company=any(e["type"] == "company" for e in ents)
        )
        candidates.append(
            {
                "src": src,
                "item": it,
                "canonical": canon,
                "entities": ents,
                "region": region,
                "category": category,
                "reason": reason,
                "fp": dedupe.fingerprint(it.title),
            }
        )

    async with session_factory()() as db:
        # Layer 1: exact canonical URL already stored
        existing: set[str] = set()
        canon_list = [c["canonical"] for c in candidates]
        for i in range(0, len(canon_list), 400):
            chunk = canon_list[i : i + 400]
            existing |= set(
                (
                    await db.execute(
                        select(FeedItem.canonical_url).where(FeedItem.tenant_id == ctx.tenant.id, FeedItem.canonical_url.in_(chunk))
                    )
                ).scalars()
            )
        fresh = [c for c in candidates if c["canonical"] not in existing]
        stats["dup_url"] += len(candidates) - len(fresh)

        recent = list(
            (
                await db.execute(
                    select(FeedItem).where(FeedItem.tenant_id == ctx.tenant.id, FeedItem.fetched_at >= now - timedelta(days=14))
                )
            ).scalars()
        )
        recent_5d = [r for r in recent if r.fetched_at >= now - timedelta(days=5)]

        # Similarity index over recent + fresh (TF-IDF; embeddings when available)
        docs = [f"{r.title} {r.summary or ''}" for r in recent] + [f"{c['item'].title} {c['item'].summary}" for c in fresh]
        index = dedupe.TfidfIndex(docs) if docs else None
        recent_vecs = index.vectors[: len(recent)] if index else []
        fresh_vecs = index.vectors[len(recent) :] if index else []

        embeddings: list[list[float]] | None = None
        if fresh and dcfg.get("embeddings", True) and ctx.settings.model_embed:
            try:
                embeddings = await ctx.provider.embed(
                    model=ctx.settings.model_embed, texts=[f"{c['item'].title}. {c['item'].summary[:300]}" for c in fresh]
                )
                if len(embeddings) != len(fresh):
                    embeddings = None
            except Exception as exc:  # embeddings are optional; TF-IDF covers the gap
                log.info("embeddings unavailable, using TF-IDF: %s", exc)
                embeddings = None

        inserted: list[FeedItem] = []
        batch_fps: list[tuple[str, FeedItem]] = []
        for i, c in enumerate(fresh):
            if len(inserted) >= max_items:
                break
            it: RawItem = c["item"]
            cluster_id: uuid.UUID | None = None
            status = "new"
            # Layer 2: SimHash title fingerprint
            for r in recent_5d:
                if r.title_fingerprint and dedupe.is_title_duplicate(c["fp"], r.title_fingerprint):
                    cluster_id = r.dedupe_cluster_id or r.id
                    stats["dup_title"] += 1
                    break
            if cluster_id is None:
                for fp, other in batch_fps:
                    if dedupe.is_title_duplicate(c["fp"], fp):
                        cluster_id = other.dedupe_cluster_id or other.id
                        stats["dup_title"] += 1
                        break
            # Layer 3: semantic similarity -> cluster (and novelty)
            max_sim = 0.0
            best_match: FeedItem | None = None
            for j, r in enumerate(recent):
                if embeddings is not None and r.embedding:
                    sim = dedupe.cosine_dense(embeddings[i], r.embedding)
                    threshold = dedupe.EMBED_THRESHOLD
                else:
                    sim = dedupe.TfidfIndex.cosine(fresh_vecs[i], recent_vecs[j]) if index else 0.0
                    threshold = dedupe.TFIDF_THRESHOLD
                if sim > max_sim:
                    max_sim = sim
                if sim >= threshold and r.fetched_at >= now - timedelta(days=5) and (best_match is None or sim > max_sim - 1e-9):
                    best_match = r
            for _fp, other in batch_fps:
                if other.embedding is not None and embeddings is not None:
                    sim = dedupe.cosine_dense(embeddings[i], other.embedding)
                    threshold = dedupe.EMBED_THRESHOLD
                else:
                    sim = dedupe.TfidfIndex.cosine(fresh_vecs[i], index.vector(f"{other.title} {other.summary or ''}")) if index else 0.0
                    threshold = dedupe.TFIDF_THRESHOLD
                max_sim = max(max_sim, sim)
                if sim >= threshold and best_match is None:
                    best_match = other
            if cluster_id is None and best_match is not None:
                cluster_id = best_match.dedupe_cluster_id or best_match.id
                stats["clustered"] += 1
            total, breakdown, signals = scoring.score(
                published_at=it.published_at,
                now=now,
                entities=c["entities"],
                text=f"{it.title} {it.summary}",
                source_weight=c["src"].weight,
                max_similarity=max_sim if cluster_id is None else 1.0,
                weights=weights,
            )
            row = FeedItem(
                id=uuid.uuid4(),  # assigned now so later items in this batch can cluster onto it before flush
                tenant_id=ctx.tenant.id,
                source_id=c["src"].id,
                title=it.title[:500],
                url=it.url,
                canonical_url=c["canonical"],
                publisher=it.publisher or c["src"].name,
                summary=truncate_words(it.summary, 600) if it.summary else None,
                published_at=it.published_at,
                fetched_at=now,
                lang=(it.lang or "en")[:8],
                entities=c["entities"],
                region=c["region"],
                score=total,
                score_breakdown={**breakdown, "signals": signals},
                suggested_category=c["category"],
                category_reason=c["reason"],
                title_fingerprint=c["fp"],
                dedupe_cluster_id=cluster_id,
                is_cluster_head=cluster_id is None,
                embedding=embeddings[i] if embeddings is not None else None,
                status="new" if cluster_id is None else "duplicate",
            )
            if cluster_id is not None:
                status = "duplicate"
            row.status = status
            db.add(row)
            inserted.append(row)
            batch_fps.append((c["fp"], row))
        await db.flush()

        # Cluster heads: highest-scoring member is the head; others are marked duplicate.
        cluster_ids = {r.dedupe_cluster_id for r in inserted if r.dedupe_cluster_id}
        for cid in cluster_ids:
            members = list(
                (
                    await db.execute(
                        select(FeedItem).where(
                            FeedItem.tenant_id == ctx.tenant.id, (FeedItem.dedupe_cluster_id == cid) | (FeedItem.id == cid)
                        )
                    )
                ).scalars()
            )
            for m in members:
                if m.dedupe_cluster_id is None:
                    m.dedupe_cluster_id = cid
            head = max(members, key=lambda m: (m.status in ("promoted",), m.score))
            for m in members:
                m.is_cluster_head = m.id == head.id
                if m.is_cluster_head and m.status == "duplicate":
                    m.status = "new"
                elif not m.is_cluster_head and m.status in ("new", "triaged"):
                    m.status = "duplicate"

        # Source health
        threshold = int(dcfg.get("auto_disable_after_failures", 5))
        for h in health:
            src = await db.get(Source, h["id"])
            if src is None:
                continue
            src.last_fetched_at = now
            src.last_latency_ms = h["latency"]
            src.last_item_count = h["count"]
            if h["error"]:
                src.last_error = h["error"][:1000]
                src.consecutive_failures += 1
                if src.consecutive_failures >= threshold and src.active:
                    src.active = False
                    audit(db, tenant_id=ctx.tenant.id, actor_type="agent", actor_id="discovery", action="source.auto_disabled",
                          entity="source", entity_id=src.id, detail={"failures": src.consecutive_failures, "error": src.last_error})
            else:
                src.last_error = None
                src.consecutive_failures = 0
        await db.commit()
        new_heads = sorted((r for r in inserted if r.is_cluster_head), key=lambda r: r.score, reverse=True)
        head_ids = [r.id for r in new_heads]

    await ctx.log(
        f"Stored {len(inserted)} new item(s): {len(head_ids)} unique stories, "
        f"{stats['dup_title'] + stats['clustered']} clustered as duplicates"
    )

    enriched = await _enrich(ctx, head_ids[: int(dcfg.get("enrich_top_k", 12))]) if dcfg.get("llm_enrich", True) else 0

    duration = int((time.perf_counter() - started) * 1000)
    summary = {
        "sources": len(sources),
        "sources_ok": ok_sources,
        "sources_failed": len(sources) - ok_sources,
        "new_items": len(inserted),
        "unique_stories": len(head_ids),
        "enriched": enriched,
        "duration_ms": duration,
        **stats,
    }
    async with session_factory()() as db:
        state = (
            await db.execute(select(KVState).where(KVState.tenant_id == ctx.tenant.id, KVState.key == "discovery.last_run"))
        ).scalar_one_or_none()
        if state is None:
            state = KVState(tenant_id=ctx.tenant.id, key="discovery.last_run", value={})
            db.add(state)
        state.value = {"at": utcnow().isoformat(), **summary}
        state.updated_at = utcnow()
        audit(db, tenant_id=ctx.tenant.id, actor_type="agent", actor_id="discovery", action="discovery.run", entity="feed", detail=summary)
        await db.commit()
    return summary


async def _enrich(ctx: AgentContext, ids: list[uuid.UUID]) -> int:
    if not ids:
        return 0
    async with session_factory()() as db:
        system, used = await compose_system(db, ctx.tenant.id, agent="discovery", include_persona=False, include_style=False)
    done = 0
    for fid in ids:
        async with session_factory()() as db:
            item = await db.get(FeedItem, fid)
            if item is None:
                continue
            prompt = (
                "Classify this news item for The Executive Narrative.\n"
                f"Title: {item.title}\nPublisher: {item.publisher}\nSummary: {item.summary or '(none)'}\n"
                f"Rules-based suggestion: {item.suggested_category} ({item.category_reason})\n"
                "Return the best category key, your confidence (0–1), a one-line why_it_matters (<=140 chars, "
                "for a senior leader, no hype) and up to 8 entities."
            )
            try:
                out, _run = await structured(
                    ctx, agent="discovery", task="classify", system=system, prompt=prompt, schema=Classification,
                    context={"title": item.title, "summary": item.summary or "", "rules_category": item.suggested_category},
                    prompt_version=versions_tag(used), max_repairs=1,
                )
            except JobError as exc:
                await ctx.log(f"Enrichment stopped: {exc}", level="warn")
                break
            item.why_it_matters = truncate_words(out.why_it_matters, 140)
            if out.category != item.suggested_category and out.confidence >= 0.75:
                item.category_reason = f"Model override ({out.confidence:.2f}): was {item.suggested_category} — {item.category_reason}"
                item.suggested_category = out.category
            known = {e["name"].lower() for e in item.entities or []}
            extra = [{"name": e.name, "type": e.type, "prominence": 0.6, "watchlist": False} for e in out.entities if e.name.lower() not in known]
            if extra:
                item.entities = [*(item.entities or []), *extra][:15]
            item.status = "triaged" if item.status == "new" else item.status
            await db.commit()
            done += 1
    if done:
        await ctx.log(f"Classified {done} top stories with the fast model")
    return done
