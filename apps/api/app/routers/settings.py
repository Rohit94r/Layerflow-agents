"""Settings endpoints (plan §8.8): tenant, prompts (versioned), persona & style, models, integrations
(secrets write-only), LinkedIn OAuth, evaluations, users, danger zone."""

from __future__ import annotations

import asyncio
import json
import secrets as pysecrets
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import linkedin
from app.agents.evals import load_cases
from app.agents.publisher import adapter_for
from app.core.audit import audit
from app.core.config import get_settings
from app.core.deps import ROLE_ADMIN, ROLE_CONTENT, Principal, current_principal, get_db, require
from app.core.errors import ApiError, bad_request
from app.core.security import hash_password, sign
from app.models import EvalRun, Tenant, User
from app.providers.registry import get_provider
from app.queue.jobs import enqueue
from app.routers.common import owned
from app.schemas import EvalRunIn, IntegrationsIn, IntegrationTestIn, MaintenanceIn, ModelsIn, ModelTestIn, PersonaPut, PromptActivate, PromptPut, TenantPatch
from app.serializers import eval_run_out, job_out, tenant_out, user_out
from app.services import banned as banned_mod
from app.services import prompts as prompt_store
from app.services.integrations import (
    get_secret,
    integration_config,
    linkedin_state,
    secret_flags,
    set_linkedin_state,
    set_secret,
)
from app.services.tenant_settings import AGENT_KEYS, deep_merge, effective, validate_scoring

router = APIRouter(prefix="/settings", tags=["settings"])


# ---------------- tenant ----------------
@router.get("/tenant")
async def get_tenant(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, principal.tenant_id)
    eff = effective(tenant.settings)
    eff.pop("integrations", None)
    return {"tenant": tenant_out(tenant), "settings": eff}


@router.patch("/tenant")
async def patch_tenant(body: TenantPatch, principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, principal.tenant_id)
    if body.timezone:
        try:
            ZoneInfo(body.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise bad_request("invalid_timezone", f"Unknown timezone '{body.timezone}'") from exc
        tenant.timezone = body.timezone
    if body.name:
        tenant.name = body.name
    if body.domain is not None:
        tenant.domain = body.domain or None
    if body.settings:
        incoming = dict(body.settings)
        incoming.pop("integrations", None)  # managed by /settings/integrations
        incoming.pop("models", None)  # managed by /settings/models
        if "scoring" in incoming:
            incoming["scoring"] = validate_scoring(incoming["scoring"])
        if "spelling" in incoming and incoming["spelling"] not in ("en-US", "en-GB"):
            raise bad_request("invalid_spelling", "spelling must be en-US or en-GB")
        cadence = incoming.get("cadence") or {}
        for slot in cadence.get("slots", []) or []:
            try:
                hh, mm = slot.split(":")
                assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60
            except (ValueError, AssertionError) as exc:
                raise bad_request("invalid_slot", f"Invalid cadence slot '{slot}' (use HH:MM)") from exc
        tenant.settings = deep_merge(tenant.settings or {}, incoming)
    audit(db, tenant_id=tenant.id, actor_type="user", actor_id=principal.user.id, action="settings.tenant", entity="tenant", entity_id=tenant.id,
          detail={"keys": list((body.settings or {}).keys())})
    await db.commit()
    eff = effective(tenant.settings)
    eff.pop("integrations", None)
    return {"tenant": tenant_out(tenant), "settings": eff}


# ---------------- prompts ----------------
@router.get("/prompts")
async def list_prompts(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    items = []
    for key in prompt_store.list_keys():
        ref = await prompt_store.get_prompt(db, principal.tenant_id, key)
        items.append({"key": key, "version": ref.version, "source": ref.source, "chars": len(ref.body)})
    return {"items": items}


@router.post("/prompts/{key:path}/activate")
async def activate_prompt(key: str, body: PromptActivate, principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    if key not in prompt_store.list_keys():
        raise ApiError(404, "not_found", "Prompt not found")
    await prompt_store.activate(db, principal.tenant_id, key, body.version_id)
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="prompt.activate", entity="prompt", entity_id=key, detail={"version_id": body.version_id})
    await db.commit()
    return await get_prompt(key, principal, db)


@router.get("/prompts/{key:path}")
async def get_prompt(key: str, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    if key not in prompt_store.list_keys():
        raise ApiError(404, "not_found", "Prompt not found")
    ref = await prompt_store.get_prompt(db, principal.tenant_id, key)
    return {
        "key": key,
        "active": {"version": ref.version, "body": ref.body, "source": ref.source, "id": ref.id or "file"},
        "versions": await prompt_store.versions(db, principal.tenant_id, key),
    }


@router.put("/prompts/{key:path}")
async def put_prompt(key: str, body: PromptPut, principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    if key not in prompt_store.list_keys():
        raise ApiError(404, "not_found", "Prompt not found")
    row = await prompt_store.save_version(db, principal.tenant_id, key, body.body, user_id=principal.user.id, note=body.note)
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="prompt.save", entity="prompt", entity_id=key,
          detail={"version": row.version, "note": body.note, "eval_reminder": "Run an evaluation after prompt changes"})
    await db.commit()
    return await get_prompt(key, principal, db)


# ---------------- persona & style ----------------
@router.get("/persona")
async def get_persona(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    persona = await prompt_store.get_prompt(db, principal.tenant_id, "persona/ten")
    structure = await prompt_store.get_prompt(db, principal.tenant_id, "style/structure")
    lexicon = await prompt_store.get_prompt(db, principal.tenant_id, "style/lexicon")
    banned = await prompt_store.banned_list(db, principal.tenant_id)
    profile_path = get_settings().evals_dir / "style" / "style_profile.json"
    profile = None
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except ValueError:
            profile = None
    return {
        "persona": {"key": "persona/ten", "version": persona.version, "body": persona.body, "source": persona.source},
        "structure": {"version": structure.version, "body": structure.body},
        "lexicon": {"version": lexicon.version, "body": lexicon.body},
        "banned_phrases": banned,
        "style_profile": profile,
    }


@router.put("/persona")
async def put_persona(body: PersonaPut, principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    if body.persona:
        await prompt_store.save_version(db, principal.tenant_id, "persona/ten", body.persona, user_id=principal.user.id, note=body.note)
    if body.banned_phrases is not None:
        phrases = sorted({p.strip().lower() for p in body.banned_phrases if len(p.strip()) >= 3})
        text = "# Banned phrases (edited in Settings)\n" + "\n".join(phrases) + "\n"
        await prompt_store.save_version(db, principal.tenant_id, "style/banned", text, user_id=principal.user.id, note=body.note or "Banned list edit")
        banned_mod.reload()
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="settings.persona", entity="prompt", entity_id="persona/ten")
    await db.commit()
    return await get_persona(principal, db)


# ---------------- models ----------------
@router.get("/models")
async def get_models(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    s = get_settings()
    tenant = await db.get(Tenant, principal.tenant_id)
    eff = effective(tenant.settings)
    provider = get_provider()
    h = await provider.health()
    return {
        "provider": provider.name,
        "base_url": h.base_url,
        "reachable": h.ok,
        "available": h.models,
        "defaults": {"writer": s.model_writer, "fast": s.model_fast, "embed": s.model_embed, "num_ctx": s.model_num_ctx, "timeout_s": s.model_timeout_s, "concurrency": s.model_concurrency},
        "agents": {k: eff["models"]["agents"].get(k, {}) for k in AGENT_KEYS},
        "detail": h.detail,
    }


@router.post("/models")
async def set_models(body: ModelsIn, principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, principal.tenant_id)
    unknown = [k for k in body.agents if k not in AGENT_KEYS]
    if unknown:
        raise bad_request("unknown_agent", f"Unknown agent(s): {', '.join(unknown)}")
    patch = {"models": {"agents": {k: v.model_dump(exclude_none=True) for k, v in body.agents.items()}}}
    tenant.settings = deep_merge(tenant.settings or {}, patch)
    audit(db, tenant_id=tenant.id, actor_type="user", actor_id=principal.user.id, action="settings.models", entity="tenant", entity_id=tenant.id, detail=patch)
    await db.commit()
    return await get_models(principal, db)


@router.post("/models/test")
async def test_model(body: ModelTestIn | None = None, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    provider = get_provider()
    tenant = await db.get(Tenant, principal.tenant_id)
    model = (body.model if body else None) or effective(tenant.settings)["models"]["agents"]["discovery"].get("model") or get_settings().model_fast
    h = await provider.health()
    if not h.ok:
        return {"ok": False, "model": model, "models": [], "latency_ms": None, "error": h.detail or "Provider unreachable", "sample": None}
    started = time.perf_counter()
    try:
        res = await provider.generate(
            model=model, system="You are a terse assistant.", prompt='Reply with the JSON object {"ok": true, "reply": "pong"} and nothing else.',
            schema={"type": "object", "properties": {"ok": {"type": "boolean"}, "reply": {"type": "string"}}, "required": ["ok"]},
            temperature=0.0, max_tokens=20, timeout_s=120, task="smoke",
        )
        return {
            "ok": True, "model": model, "models": h.models, "latency_ms": int((time.perf_counter() - started) * 1000),
            "sample": res.text[:200], "completion_tokens": res.completion_tokens, "error": None,
        }
    except Exception as exc:  # surface the provider's message verbatim
        return {"ok": False, "model": model, "models": h.models, "latency_ms": int((time.perf_counter() - started) * 1000), "sample": None, "error": str(exc)[:300]}


# ---------------- integrations ----------------
async def _integrations_view(db: AsyncSession, tenant: Tenant) -> dict[str, Any]:
    cfg = integration_config(tenant)
    flags = await secret_flags(db, tenant.id)
    li_state = await linkedin_state(db, tenant.id)
    ten = cfg["ten_static"]
    return {
        "default_target": cfg["default_target"],
        "targets": {
            "export": {"configured": True, "label": "Export bundle (ZIP)", "always_available": True},
            "ten_static": {
                "configured": True,
                "mode": "sftp" if ten.get("sftp_host") else "local",
                "site_url": ten.get("site_url"),
                "public_root": ten.get("public_root"),
                "sftp_host": ten.get("sftp_host"),
                "sftp_port": ten.get("sftp_port"),
                "sftp_user": ten.get("sftp_user"),
                "sftp_key_path": ten.get("sftp_key_path"),
                "password_configured": flags["ten_sftp_password"],
                "note": None if ten.get("sftp_host") else "No SFTP host: pages publish to the local staging site at /site/<tenant>/…",
            },
            "wordpress": {"configured": bool(cfg["wordpress"].get("url") and flags["wordpress_app_password"]), **cfg["wordpress"], "password_configured": flags["wordpress_app_password"]},
            "webhook": {"configured": bool(cfg["webhook"].get("url") and flags["webhook_secret"]), **cfg["webhook"], "secret_configured": flags["webhook_secret"]},
        },
        "linkedin": {
            "client_id": cfg["linkedin"].get("client_id"),
            "client_id_set": bool(cfg["linkedin"].get("client_id")),
            "client_secret_set": flags["linkedin_client_secret"],
            "redirect_uri": cfg["linkedin"].get("redirect_uri"),
            "org_urn": cfg["linkedin"].get("org_urn"),
            "author_type": cfg["linkedin"].get("author_type"),
            "connected": flags["linkedin_access_token"],
            "author_urn": li_state.get("author_urn"),
            "expires_at": li_state.get("expires_at"),
            "last_refresh_error": li_state.get("last_refresh_error"),
        },
    }


@router.get("/integrations")
async def get_integrations(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, principal.tenant_id)
    return await _integrations_view(db, tenant)


@router.put("/integrations")
async def put_integrations(body: IntegrationsIn, principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, principal.tenant_id)
    patch: dict[str, Any] = {}
    secret_updates: dict[str, str | None] = {}
    allowed = {
        "ten_static": ({"site_url", "public_root", "sftp_host", "sftp_port", "sftp_user", "sftp_key_path"}, {"sftp_password": "ten_sftp_password"}),
        "wordpress": ({"url", "user"}, {"app_password": "wordpress_app_password"}),
        "webhook": ({"url"}, {"secret": "webhook_secret"}),
        "linkedin": ({"client_id", "org_urn", "author_type", "redirect_uri"}, {"client_secret": "linkedin_client_secret", "access_token": "linkedin_access_token"}),
    }
    for section, (plain, secret_map) in allowed.items():
        data = getattr(body, section)
        if not data:
            continue
        unknown = set(data) - plain - set(secret_map)
        if unknown:
            raise bad_request("unknown_field", f"Unknown {section} field(s): {', '.join(sorted(unknown))}")
        clean = {k: (str(v).strip() if v is not None else "") for k, v in data.items() if k in plain}
        if section == "linkedin" and clean.get("author_type") not in (None, "", "organization", "member"):
            raise bad_request("invalid_author_type", "author_type must be organization or member")
        if clean:
            patch.setdefault("integrations", {})[section] = clean
        for field, key in secret_map.items():
            if field in data:
                secret_updates[key] = (data[field] or "").strip() or None
    if body.default_target:
        patch["publishing"] = {"default_target": body.default_target}
    if patch:
        tenant.settings = deep_merge(tenant.settings or {}, patch)
    for key, value in secret_updates.items():
        await set_secret(db, tenant.id, key, value)
        if key == "linkedin_access_token" and value:
            # Manually pasted token (e.g. from the LinkedIn token generator): look up the member URN once.
            state = await linkedin_state(db, tenant.id)
            try:
                state["author_urn"] = await linkedin.member_urn(value)
            except linkedin.LinkedInError as exc:
                state["last_refresh_error"] = str(exc)
            state["issued_at"] = datetime.now(UTC).isoformat()
            await set_linkedin_state(db, tenant.id, state)
    audit(db, tenant_id=tenant.id, actor_type="user", actor_id=principal.user.id, action="settings.integrations", entity="tenant", entity_id=tenant.id,
          detail={"sections": [s for s in allowed if getattr(body, s)], "secrets_changed": sorted(secret_updates)})
    await db.commit()
    return await _integrations_view(db, tenant)


@router.post("/integrations/test")
async def test_integration(body: IntegrationTestIn, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, principal.tenant_id)
    cfg = integration_config(tenant)
    if body.target == "linkedin":
        from app.agents.distribution import valid_token

        token, author, reason = await valid_token(db, tenant)
        return {"ok": token is not None, "detail": f"Connected as {author}" if token else reason}
    if body.target == "export":
        ok, detail = await adapter_for("export").health()
        return {"ok": ok, "detail": detail}
    if body.target == "ten_static":
        ten = cfg["ten_static"]
        if not ten.get("sftp_host"):
            from pathlib import Path

            root = Path(get_settings().site_root) / tenant.slug
            root.mkdir(parents=True, exist_ok=True)
            return {"ok": True, "detail": f"Local staging mode: writing to {root} (served at /site/{tenant.slug}/)"}

        pw = await get_secret(db, tenant.id, "ten_sftp_password")

        def _probe() -> str:
            from app.adapters.base import PublishContext
            from app.adapters.ten_static import TenStaticAdapter

            pctx = PublishContext(tenant_id=tenant.id, tenant_slug=tenant.slug, article_id=uuid.uuid4(), category="brief", route="/brief",
                                  slug="probe", content_hash="", payload={}, html="", published_at=datetime.now(UTC), site_url=ten["site_url"], config=ten,
                                  secrets={"ten_sftp_password": pw})
            client, sftp = TenStaticAdapter()._sftp(pctx)
            try:
                return f"Connected; {len(sftp.listdir(ten.get('public_root') or '/'))} entries in {ten.get('public_root')}"
            finally:
                sftp.close()
                client.close()

        try:
            return {"ok": True, "detail": await asyncio.to_thread(_probe)}
        except Exception as exc:
            return {"ok": False, "detail": str(exc)[:300]}
    if body.target == "wordpress":
        wp = cfg["wordpress"]
        pw = await get_secret(db, tenant.id, "wordpress_app_password")
        if not (wp.get("url") and wp.get("user") and pw):
            return {"ok": False, "detail": "WordPress URL, user and application password are required"}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(f"{wp['url'].rstrip('/')}/wp-json/wp/v2/users/me", auth=(wp["user"], pw))
            return {"ok": r.status_code == 200, "detail": f"HTTP {r.status_code}" + (f" — signed in as {r.json().get('name')}" if r.status_code == 200 else "")}
        except httpx.HTTPError as exc:
            return {"ok": False, "detail": str(exc)[:200]}
    if body.target == "webhook":
        url = cfg["webhook"].get("url")
        secret = await get_secret(db, tenant.id, "webhook_secret")
        if not (url and secret):
            return {"ok": False, "detail": "Webhook URL and secret are required"}
        import hashlib
        import hmac

        payload = json.dumps({"event": "ping", "tenant": tenant.slug}).encode()
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(url, content=payload, headers={"Content-Type": "application/json", "X-LayerFlow-Signature": f"sha256={sig}", "X-LayerFlow-Event": "ping"})
            return {"ok": r.status_code < 300, "detail": f"HTTP {r.status_code}"}
        except httpx.HTTPError as exc:
            return {"ok": False, "detail": str(exc)[:200]}
    raise bad_request("unknown_target", "Unknown target")


@router.get("/integrations/linkedin/connect")
async def linkedin_connect(principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, principal.tenant_id)
    cfg = integration_config(tenant)["linkedin"]
    if not cfg.get("client_id") or not await get_secret(db, tenant.id, "linkedin_client_secret"):
        raise ApiError(409, "linkedin_not_configured", "Add the LinkedIn app client ID and secret first")
    nonce = pysecrets.token_urlsafe(12)
    raw = f"{tenant.id}:{principal.user.id}:{nonce}"
    state = f"{raw}:{sign(raw)[:32]}"
    return {"authorize_url": linkedin.authorize_url(cfg["client_id"], cfg["redirect_uri"], state, organization=cfg.get("author_type") == "organization")}


@router.get("/integrations/linkedin/callback")
async def linkedin_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                            principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    base = get_settings().app_base_url.rstrip("/")
    if error or not code or not state:
        return RedirectResponse(f"{base}/settings?tab=integrations&linkedin=error&reason={error or 'missing_code'}")
    parts = state.split(":")
    if len(parts) != 4 or sign(":".join(parts[:3]))[:32] != parts[3] or parts[0] != str(principal.tenant_id):
        return RedirectResponse(f"{base}/settings?tab=integrations&linkedin=error&reason=bad_state")
    tenant = await db.get(Tenant, principal.tenant_id)
    cfg = integration_config(tenant)["linkedin"]
    secret = await get_secret(db, tenant.id, "linkedin_client_secret") or ""
    try:
        data = await linkedin.exchange_code(code, cfg["client_id"], secret, cfg["redirect_uri"])
        urn = await linkedin.member_urn(data["access_token"])
    except linkedin.LinkedInError as exc:
        return RedirectResponse(f"{base}/settings?tab=integrations&linkedin=error&reason={str(exc)[:80]}")
    await set_secret(db, tenant.id, "linkedin_access_token", data["access_token"])
    if data.get("refresh_token"):
        await set_secret(db, tenant.id, "linkedin_refresh_token", data["refresh_token"])
    await set_linkedin_state(db, tenant.id, {"author_urn": urn, "issued_at": datetime.now(UTC).isoformat(), "expires_at": data.get("expires_at"), "scope": data.get("scope")})
    audit(db, tenant_id=tenant.id, actor_type="user", actor_id=principal.user.id, action="linkedin.connected", entity="tenant", entity_id=tenant.id, detail={"author_urn": urn})
    await db.commit()
    return RedirectResponse(f"{base}/settings?tab=integrations&linkedin=connected")


@router.post("/integrations/linkedin/disconnect")
async def linkedin_disconnect(principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    await set_secret(db, principal.tenant_id, "linkedin_access_token", None)
    await set_secret(db, principal.tenant_id, "linkedin_refresh_token", None)
    await set_linkedin_state(db, principal.tenant_id, {})
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="linkedin.disconnected", entity="tenant", entity_id=principal.tenant_id)
    await db.commit()
    tenant = await db.get(Tenant, principal.tenant_id)
    return await _integrations_view(db, tenant)


# ---------------- evaluations ----------------
@router.get("/evals")
async def evals(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    cases = load_cases(get_settings().evals_dir)
    runs = (await db.execute(select(EvalRun).where(EvalRun.tenant_id == principal.tenant_id).order_by(EvalRun.created_at.desc()).limit(30))).scalars().all()
    return {
        "cases": [{"id": c.get("id"), "category": c.get("category"), "label": c.get("label"), "description": c.get("description"), "expected": (c.get("expected") or {}).get("verdict")} for c in cases],
        "runs": [eval_run_out(r) for r in runs],
        "latest": eval_run_out(runs[0], include_details=True) if runs else None,
    }


@router.get("/evals/{run_id}")
async def eval_run(run_id: str, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    run = await owned(db, EvalRun, run_id, principal.tenant_id, "eval run")
    return eval_run_out(run, include_details=True)


@router.post("/evals/run")
async def run_evals(body: EvalRunIn, principal: Principal = Depends(require(ROLE_CONTENT)), db: AsyncSession = Depends(get_db)):
    job = await enqueue(db, tenant_id=principal.tenant_id, type="eval", payload={"suite": body.suite, "case_ids": body.case_ids}, dedupe_key=f"eval:{body.suite}", created_by=principal.user.id)
    await db.commit()
    return {"job": job_out(job)}


# ---------------- users ----------------
class UserIn(BaseModel):
    email: EmailStr
    name: str | None = Field(default=None, max_length=120)
    role: str = Field(pattern="^(owner|editor|reviewer)$")
    password: str = Field(min_length=10, max_length=256)


class UserPatch(BaseModel):
    role: str | None = Field(default=None, pattern="^(owner|editor|reviewer)$")
    active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=256)


@router.get("/users")
async def users(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(User).where(User.tenant_id == principal.tenant_id).order_by(User.created_at))).scalars().all()
    return {"items": [{**user_out(u), "active": u.active, "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None} for u in rows]}


@router.post("/users", status_code=201)
async def create_user(body: UserIn, principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    exists = (await db.execute(select(User.id).where(User.tenant_id == principal.tenant_id, func.lower(User.email) == body.email.lower()))).scalar_one_or_none()
    if exists:
        raise ApiError(409, "duplicate_user", "A user with this email already exists")
    user = User(tenant_id=principal.tenant_id, email=body.email.lower(), name=body.name, role=body.role, password_hash=hash_password(body.password))
    db.add(user)
    await db.flush()
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="user.create", entity="user", entity_id=user.id, detail={"role": body.role})
    await db.commit()
    return user_out(user)


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UserPatch, principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    user = await owned(db, User, user_id, principal.tenant_id, "user")
    if user.id == principal.user.id and (body.active is False or (body.role and body.role != "owner")):
        raise bad_request("self_lockout", "You cannot demote or deactivate yourself")
    if body.role:
        user.role = body.role
    if body.active is not None:
        user.active = body.active
    if body.password:
        user.password_hash = hash_password(body.password)
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action="user.update", entity="user", entity_id=user.id,
          detail={k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "password"})
    await db.commit()
    return user_out(user)


# ---------------- danger zone ----------------
@router.post("/maintenance/{action}")
async def maintenance(action: str, body: MaintenanceIn, principal: Principal = Depends(require(ROLE_ADMIN)), db: AsyncSession = Depends(get_db)):
    from app.agents import maintenance as m

    if body.confirm != principal.tenant.slug:
        raise bad_request("confirm_mismatch", f"Type the tenant slug '{principal.tenant.slug}' to confirm")
    if action == "purge_feed":
        detail: dict[str, Any] = {"deleted": await m.purge_feed(principal.tenant_id, body.older_than_days or 30)}
    elif action == "clear_dead_jobs":
        detail = {"deleted": await m.clear_dead_jobs(principal.tenant_id)}
    elif action == "revoke_sessions":
        detail = {"revoked": await m.revoke_sessions(principal.tenant_id, keep_session_id=principal.session_id)}
    elif action == "retention":
        detail = await m.apply_retention(principal.tenant_id)
    else:
        raise ApiError(404, "not_found", "Unknown maintenance action")
    audit(db, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user.id, action=f"maintenance.{action}", entity="tenant", entity_id=principal.tenant_id, detail=detail)
    await db.commit()
    return {"ok": True, "action": action, "detail": detail}

