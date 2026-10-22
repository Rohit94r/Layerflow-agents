"""Immutable article versions (plan §5.10 rule 2). Every stage writes a full snapshot; restore is one call."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.models import Article, ArticleVersion
from app.services.article_doc import clone, content_hash


async def current_payload(db: AsyncSession, article: Article) -> dict[str, Any]:
    if article.current_version_id is None:
        return {}
    v = await db.get(ArticleVersion, article.current_version_id)
    return clone(v.payload) if v else {}


async def current_version(db: AsyncSession, article: Article) -> ArticleVersion | None:
    if article.current_version_id is None:
        return None
    return await db.get(ArticleVersion, article.current_version_id)


async def add_version(
    db: AsyncSession,
    article: Article,
    *,
    stage: str,
    payload: dict[str, Any],
    created_by: uuid.UUID | None = None,
    note: str | None = None,
    model_run_id: uuid.UUID | None = None,
    prompt_version: str | None = None,
) -> ArticleVersion:
    version = ArticleVersion(
        article_id=article.id,
        stage=stage,
        payload=payload,
        created_by=created_by,
        note=note,
        model_run_id=model_run_id,
        prompt_version=prompt_version,
    )
    db.add(version)
    await db.flush()
    art = payload.get("article") or {}
    seo = payload.get("seo") or {}
    qa = payload.get("qa") or {}
    article.current_version_id = version.id
    if art.get("title"):
        article.title = art["title"][:300]
    if seo.get("slug"):
        article.slug = seo["slug"]
    if qa.get("overall") is not None:
        article.quality_score = qa["overall"]
    article.content_hash = content_hash(payload)
    article.updated_at = utcnow()
    return version


async def list_versions(db: AsyncSession, article_id: uuid.UUID) -> list[ArticleVersion]:
    return list(
        (
            await db.execute(
                select(ArticleVersion).where(ArticleVersion.article_id == article_id).order_by(ArticleVersion.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
