from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.config import get_settings
from app.core.db import utcnow
from app.core.deps import Principal, client_ip, current_principal, get_db
from app.core.errors import ApiError
from app.core.ratelimit import limiter
from app.core.security import CSRF_COOKIE, SESSION_COOKIE, hash_password, hash_token, new_token, verify_password
from app.models import Session, Tenant, User
from app.schemas import LoginIn, SetupIn
from app.serializers import tenant_out, user_out

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookies(response: Response, token: str, csrf: str) -> None:
    s = get_settings()
    max_age = s.session_days * 86400
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="lax", secure=s.secure_cookies, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, samesite="lax", secure=s.secure_cookies, path="/")


def _open_session(db: AsyncSession, user: User, request: Request) -> tuple[str, str]:
    """Create a session row and stamp the login time. Caller commits."""
    s = get_settings()
    token, csrf = new_token(), new_token()
    db.add(
        Session(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=utcnow() + timedelta(days=s.session_days),
            ip=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:400],
        )
    )
    user.last_login_at = utcnow()
    return token, csrf


async def _user_count(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(User))).scalar_one())


@router.get("/setup")
async def setup_status(db: AsyncSession = Depends(get_db)):
    """Whether the first-run "create admin account" screen should be shown."""
    return {"needs_setup": await _user_count(db) == 0}


@router.post("/setup")
async def setup(body: SetupIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Create the first owner account. Refuses once any user exists (no open sign-up)."""
    s = get_settings()
    ip = client_ip(request)
    allowed, retry = limiter.hit(f"setup:{ip}", 5, 900)
    if not allowed:
        raise ApiError(429, "rate_limited", "Too many attempts. Try again later.", {"retry_after_s": round(retry)})
    if await _user_count(db) > 0:
        raise ApiError(409, "setup_complete", "This instance already has an account. Sign in instead.")

    tenant = (
        await db.execute(select(Tenant).where(Tenant.slug == s.tenant_default).limit(1))
    ).scalar_one_or_none()
    if tenant is None:
        tenant = (await db.execute(select(Tenant).order_by(Tenant.created_at).limit(1))).scalar_one_or_none()
    if tenant is None:
        raise ApiError(400, "no_tenant", "No tenant exists yet. Run `python -m app.cli bootstrap` first.")

    user = User(
        tenant_id=tenant.id,
        email=str(body.email),
        name=body.name or "Owner",
        password_hash=hash_password(body.password),
        role="owner",
    )
    db.add(user)
    await db.flush()
    user.tenant = tenant
    token, csrf = _open_session(db, user, request)
    audit(db, tenant_id=tenant.id, actor_type="user", actor_id=user.id, action="auth.setup", entity="user", entity_id=user.id, detail={"ip": ip})
    await db.commit()
    limiter.reset(f"setup:{ip}")
    _set_cookies(response, token, csrf)
    return {"user": user_out(user), "tenant": tenant_out(tenant), "csrf_token": csrf}


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    s = get_settings()
    ip = client_ip(request)
    allowed, retry = limiter.hit(f"login:{ip}", s.login_attempts_per_15min, 900)
    if not allowed:
        raise ApiError(429, "rate_limited", "Too many sign-in attempts. Try again later.", {"retry_after_s": round(retry)})
    user = (
        await db.execute(select(User).where(func.lower(User.email) == body.email.lower(), User.active.is_(True)).limit(1))
    ).scalar_one_or_none()
    if user is None or not verify_password(user.password_hash, body.password):
        raise ApiError(401, "invalid_credentials", "Email or password is incorrect")
    token, csrf = _open_session(db, user, request)
    audit(db, tenant_id=user.tenant_id, actor_type="user", actor_id=user.id, action="auth.login", entity="user", entity_id=user.id, detail={"ip": ip})
    await db.commit()
    limiter.reset(f"login:{ip}")
    _set_cookies(response, token, csrf)
    return {"user": user_out(user), "tenant": tenant_out(user.tenant), "csrf_token": csrf}


@router.post("/logout")
async def logout(request: Request, response: Response, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await db.execute(delete(Session).where(Session.token_hash == hash_token(token)))
        audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="auth.logout", entity="user", entity_id=principal.user.id)
        await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(request: Request, principal: Principal = Depends(current_principal)):
    return {
        "user": user_out(principal.user),
        "tenant": tenant_out(principal.tenant),
        "csrf_token": request.cookies.get(CSRF_COOKIE),
        "provider": get_settings().model_provider,
    }
