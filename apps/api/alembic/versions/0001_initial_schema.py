"""Initial schema: tenancy, discovery, content, queue, publishing, social, observability, evals, SEO inventory.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.db import BigIntPK, JSONType, UTCDateTime

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _pk() -> sa.Column:
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _tenant_fk(nullable: bool = False) -> sa.Column:
    return sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=nullable)


def upgrade() -> None:
    # ---- tenancy ----
    op.create_table(
        "tenants",
        _pk(),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text()),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("settings", JSONType, nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "users",
        _pk(),
        _tenant_fk(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.Text()),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", UTCDateTime()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "email"),
    )
    op.create_table(
        "sessions",
        _pk(),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.Text()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "integration_secrets",
        _pk(),
        _tenant_fk(),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value_encrypted", sa.Text(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "key"),
    )
    op.create_table(
        "kv_state",
        _pk(),
        _tenant_fk(),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", JSONType, nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "key"),
    )
    op.create_table(
        "prompt_versions",
        _pk(),
        _tenant_fk(),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "key", "version"),
    )

    # ---- discovery ----
    op.create_table(
        "sources",
        _pk(),
        _tenant_fk(),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("region", sa.String(16)),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_fetched_at", UTCDateTime()),
        sa.Column("last_error", sa.Text()),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_item_count", sa.Integer()),
        sa.Column("last_latency_ms", sa.Integer()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "url"),
    )
    op.create_table(
        "feed_items",
        _pk(),
        _tenant_fk(),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id", ondelete="SET NULL")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text()),
        sa.Column("summary", sa.Text()),
        sa.Column("published_at", UTCDateTime()),
        sa.Column("fetched_at", UTCDateTime(), nullable=False),
        sa.Column("lang", sa.String(8)),
        sa.Column("entities", JSONType, nullable=False),
        sa.Column("region", sa.String(16)),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("score_breakdown", JSONType, nullable=False),
        sa.Column("suggested_category", sa.String(32)),
        sa.Column("category_reason", sa.Text()),
        sa.Column("why_it_matters", sa.Text()),
        sa.Column("title_fingerprint", sa.String(16)),
        sa.Column("dedupe_cluster_id", sa.Uuid()),
        sa.Column("is_cluster_head", sa.Boolean(), nullable=False),
        sa.Column("embedding", JSONType),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("ignored_reason", sa.Text()),
        sa.UniqueConstraint("tenant_id", "canonical_url"),
    )
    op.create_index("feed_items_tenant_published_idx", "feed_items", ["tenant_id", "published_at"])
    op.create_index("feed_items_tenant_status_score_idx", "feed_items", ["tenant_id", "status", "score"])

    # ---- content ----
    op.create_table(
        "topics",
        _pk(),
        _tenant_fk(),
        sa.Column("feed_item_id", sa.Uuid(), sa.ForeignKey("feed_items.id", ondelete="SET NULL")),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("angle", sa.Text()),
        sa.Column("region", sa.String(16)),
        sa.Column("notes", sa.Text()),
        sa.Column("links", JSONType, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "articles",
        _pk(),
        _tenant_fk(),
        sa.Column("topic_id", sa.Uuid(), sa.ForeignKey("topics.id", ondelete="SET NULL")),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(80)),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("current_version_id", sa.Uuid()),
        sa.Column("quality_score", sa.Float()),
        sa.Column("revision_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("published_url", sa.Text()),
        sa.Column("prompt_versions", JSONType, nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    op.create_index("articles_tenant_state_updated_idx", "articles", ["tenant_id", "state", "updated_at"])
    op.create_table(
        "article_versions",
        _pk(),
        sa.Column("article_id", sa.Uuid(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("payload", JSONType, nullable=False),
        sa.Column("prompt_version", sa.Text()),
        sa.Column("model_run_id", sa.Uuid()),
        sa.Column("note", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("article_versions_article_idx", "article_versions", ["article_id", "created_at"])
    op.create_table(
        "research_packs",
        _pk(),
        sa.Column("article_id", sa.Uuid(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", JSONType, nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "review_actions",
        _pk(),
        sa.Column("article_id", sa.Uuid(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("diff", JSONType),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )

    # ---- queue ----
    op.create_table(
        "jobs",
        _pk(),
        _tenant_fk(),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("article_id", sa.Uuid()),
        sa.Column("payload", JSONType, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", UTCDateTime(), nullable=False),
        sa.Column("locked_at", UTCDateTime()),
        sa.Column("locked_by", sa.Text()),
        sa.Column("last_error", sa.Text()),
        sa.Column("result", JSONType),
        sa.Column("created_by", sa.Uuid()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("started_at", UTCDateTime()),
        sa.Column("finished_at", UTCDateTime()),
    )
    op.create_index(
        "jobs_claim_idx",
        "jobs",
        ["status", "available_at", "priority"],
        postgresql_where=sa.text("status = 'queued'"),
        sqlite_where=sa.text("status = 'queued'"),
    )
    op.create_index("jobs_article_idx", "jobs", ["article_id", "created_at"])
    op.create_table(
        "job_events",
        sa.Column("id", BigIntPK, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid()),
        sa.Column("article_id", sa.Uuid()),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", JSONType),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("job_events_article_idx", "job_events", ["article_id", "id"])

    # ---- publishing & social ----
    op.create_table(
        "publications",
        _pk(),
        _tenant_fk(),
        sa.Column("article_id", sa.Uuid(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.Uuid()),
        sa.Column("target", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("scheduled_at", UTCDateTime()),
        sa.Column("published_at", UTCDateTime()),
        sa.Column("remote_id", sa.Text()),
        sa.Column("live_url", sa.Text()),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("last_error", sa.Text()),
        sa.Column("artifact_path", sa.Text()),
        sa.Column("warnings", JSONType, nullable=False),
        sa.Column("late", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "social_posts",
        _pk(),
        _tenant_fk(),
        sa.Column("article_id", sa.Uuid(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("hook", sa.Text()),
        sa.Column("cta", sa.Text()),
        sa.Column("link", sa.Text()),
        sa.Column("hashtags", JSONType, nullable=False),
        sa.Column("image_url", sa.Text()),
        sa.Column("image_spec", JSONType),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("remote_urn", sa.Text()),
        sa.Column("published_at", UTCDateTime()),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )

    # ---- observability ----
    op.create_table(
        "model_runs",
        _pk(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("agent", sa.String(64), nullable=False),
        sa.Column("job_id", sa.Uuid()),
        sa.Column("article_id", sa.Uuid()),
        sa.Column("prompt_version", sa.Text()),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(32)),
        sa.Column("params", JSONType),
        sa.Column("input_hash", sa.String(64)),
        sa.Column("output_hash", sa.String(64)),
        sa.Column("output", JSONType),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("repairs", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("model_runs_tenant_agent_idx", "model_runs", ["tenant_id", "agent", "created_at"])
    op.create_table(
        "audit_log",
        sa.Column("id", BigIntPK, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.Text()),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Text()),
        sa.Column("detail", JSONType),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("audit_log_tenant_created_idx", "audit_log", ["tenant_id", "created_at"])

    # ---- evaluation ----
    op.create_table(
        "eval_cases",
        _pk(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("case_key", sa.String(64)),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("input", JSONType, nullable=False),
        sa.Column("expected", JSONType),
        sa.Column("label", sa.String(16)),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "eval_runs",
        _pk(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("agent", sa.String(64), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("scores", JSONType, nullable=False),
        sa.Column("details", JSONType, nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )

    # ---- SEO inventory + worker heartbeats ----
    op.create_table(
        "site_pages",
        _pk(),
        _tenant_fk(),
        sa.Column("site", sa.String(64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer()),
        sa.Column("title", sa.Text()),
        sa.Column("h1", sa.Text()),
        sa.Column("headline", sa.Text()),
        sa.Column("meta_description", sa.Text()),
        sa.Column("canonical", sa.Text()),
        sa.Column("og", JSONType, nullable=False),
        sa.Column("has_jsonld", sa.Boolean(), nullable=False),
        sa.Column("word_count", sa.Integer()),
        sa.Column("headings", JSONType, nullable=False),
        sa.Column("first_paragraph", sa.Text()),
        sa.Column("signals", JSONType, nullable=False),
        sa.Column("fetched_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "site", "url"),
    )
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(128), primary_key=True),
        sa.Column("started_at", UTCDateTime(), nullable=False),
        sa.Column("last_seen", UTCDateTime(), nullable=False),
        sa.Column("info", JSONType, nullable=False),
    )

    # Postgres-only search indexes (plan §7.3). pg_trgm is created by infra/postgres/init.sql; skip if absent.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE INDEX IF NOT EXISTS feed_items_entities_gin ON feed_items USING gin (entities)")
        has_trgm = bind.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")).scalar()
        if has_trgm:
            op.execute("CREATE INDEX IF NOT EXISTS feed_items_title_trgm ON feed_items USING gin (title gin_trgm_ops)")


def downgrade() -> None:
    for table in (
        "worker_heartbeats",
        "site_pages",
        "eval_runs",
        "eval_cases",
        "audit_log",
        "model_runs",
        "social_posts",
        "publications",
        "job_events",
        "jobs",
        "review_actions",
        "research_packs",
        "article_versions",
        "articles",
        "topics",
        "feed_items",
        "sources",
        "prompt_versions",
        "kv_state",
        "integration_secrets",
        "sessions",
        "users",
        "tenants",
    ):
        op.drop_table(table)
