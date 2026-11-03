"""Source catalog groups/tiers and lead images for feed items and articles.

Revision ID: 0002_images
Revises: 0001_initial
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.db import UTCDateTime

revision: str = "0002_images"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sources") as batch:
        batch.add_column(sa.Column("group", sa.String(32)))
        batch.add_column(sa.Column("tier", sa.String(16)))

    with op.batch_alter_table("feed_items") as batch:
        batch.add_column(sa.Column("image_url", sa.Text()))
        batch.add_column(sa.Column("image_width", sa.Integer()))
        batch.add_column(sa.Column("image_height", sa.Integer()))
        batch.add_column(sa.Column("image_source", sa.String(16)))
        batch.add_column(sa.Column("image_checked_at", UTCDateTime()))

    with op.batch_alter_table("articles") as batch:
        batch.add_column(sa.Column("cover_image_url", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("articles") as batch:
        batch.drop_column("cover_image_url")

    with op.batch_alter_table("feed_items") as batch:
        batch.drop_column("image_checked_at")
        batch.drop_column("image_source")
        batch.drop_column("image_height")
        batch.drop_column("image_width")
        batch.drop_column("image_url")

    with op.batch_alter_table("sources") as batch:
        batch.drop_column("tier")
        batch.drop_column("group")
