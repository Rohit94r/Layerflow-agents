"""Request dependencies: DB session, authenticated user, CSRF and per-session rate limits, role guards."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import session_factory, utcnow
from app.core.errors import ApiError, forbidden
from app.core.ratelimit import limiter
from app.core.security import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, constant_time_equals, hash_token
from app.models import Session, Tenant, User

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

ROLE_ADMIN = frozenset({"owner"})
ROLE_CONTENT = frozenset({"owner", "editor"})
ROLE_REVIEW = frozenset({"owner", "editor", "reviewer"})
ROLE_PUBLISH = frozenset({"owner", "editor", "reviewer"})


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        yield session


@dataclass
class Principal:
    user: User
    tenant: Tenant
    session_id: str

    @property
    def tenant_id(self):
        return self.tenant.id

    @property
    def role(self) -> str:
        return self.user.role

    def can(self, roles: frozenset[str]) -> bool:
        return self.user.role in roles


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def current_principal(request: Request, db: AsyncSession = Depends(get_db)) -> Principal:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise ApiError(401, "unauthenticated", "Sign in to continue")
    row = (
        await db.execute(
            select(Session, User)
            .join(User, User.id == Session.user_id)
            .where(Session.token_hash == hash_token(token))
        )
    ).first()
    if row is None:
        raise ApiError(401, "unauthenticated", "Session expired or invalid")
    sess, user = row
    if sess.expires_at < utcnow() or not user.active:
        raise ApiError(401, "unauthenticated", "Session expired")

    settings = get_settings()
    if request.method not in SAFE_METHODS:
        header = request.headers.get(CSRF_HEADER, "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not header or not cookie or not constant_time_equals(header, cookie):
            raise ApiError(403, "csrf_failed", "Missing or invalid CSRF token. Reload the page and try again.")
        allowed, retry = limiter.hit(f"mut:{sess.id}", settings.rate_limit_mutations_per_min, 60)
    else:
        allowed, retry = limiter.hit(f"read:{sess.id}", settings.rate_limit_reads_per_min, 60)
    if not allowed:
        raise ApiError(429, "rate_limited", "Too many requests, slow down.", {"retry_after_s": round(retry, 1)})

    tenant = user.tenant
    return Principal(user=user, tenant=tenant, session_id=str(sess.id))


def require(roles: frozenset[str]) -> Callable:
    async def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.can(roles):
            raise forbidden(f"Your role ({principal.role}) cannot perform this action")
        return principal

    return _dep
