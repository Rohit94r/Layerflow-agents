"""Database engine, session factory and portable column types.

Production runs on PostgreSQL 16. Tests and laptop development can run on SQLite; the column types
below keep the schema identical on both (JSONB on Postgres, JSON on SQLite; UTC-aware timestamps).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import JSON, BigInteger, DateTime, Integer, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings

JSONType = JSON().with_variant(JSONB(), "postgresql")
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC timestamps on every backend (SQLite drops tzinfo otherwise)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC)
        if dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=15000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def init_engine(url: str | None = None) -> AsyncEngine:
    global _engine, _sessionmaker
    settings = get_settings()
    url = url or settings.database_url
    kwargs: dict = {"echo": settings.db_echo, "future": True}
    if url.startswith("sqlite"):
        db_path = url.split("///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"timeout": 15}
    else:
        kwargs.update(pool_size=10, max_overflow=10, pool_pre_ping=True)
    _engine = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):
        event.listen(_engine.sync_engine, "connect", _sqlite_pragmas)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
