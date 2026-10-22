"""The hand-written initial migration must produce exactly the schema the ORM models describe."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.db import Base

API_DIR = Path(__file__).resolve().parents[1]


def test_migration_matches_models(tmp_path):
    db_file = tmp_path / "migrated.db"
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.attributes["url"] = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")

    con = sqlite3.connect(db_file)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'")}
        assert tables == set(Base.metadata.tables), tables ^ set(Base.metadata.tables)
        for name, table in Base.metadata.tables.items():
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({name})")}
            assert cols == {c.name for c in table.columns}, (name, cols ^ {c.name for c in table.columns})
    finally:
        con.close()
    command.downgrade(cfg, "base")
