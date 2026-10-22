"""Integration configuration. Non-secret values live in tenant settings; secrets are Fernet-encrypted in
integration_secrets and are write-only through the API (the dashboard sees configured/missing, never values).
Environment variables are the fallback for both."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.security import decrypt_secret, encrypt_secret
from app.models import IntegrationSecret, KVState, Tenant

SECRET_KEYS = frozenset(
    {
        "wordpress_app_password",
        "webhook_secret",
        "linkedin_client_secret",
        "linkedin_access_token",
        "linkedin_refresh_token",
        "ten_sftp_password",
    }
)
ENV_SECRET = {
    "wordpress_app_password": "wordpress_app_password",
    "webhook_secret": "webhook_secret",
    "linkedin_client_secret": "linkedin_client_secret",
}


async def get_secret(db: AsyncSession, tenant_id: uuid.UUID, key: str) -> str | None:
    row = (
        await db.execute(select(IntegrationSecret).where(IntegrationSecret.tenant_id == tenant_id, IntegrationSecret.key == key))
    ).scalar_one_or_none()
    if row is not None:
        value = decrypt_secret(row.value_encrypted)
        if value:
            return value
    env_attr = ENV_SECRET.get(key)
    if env_attr:
        return getattr(get_settings(), env_attr) or None
    return None


async def set_secret(db: AsyncSession, tenant_id: uuid.UUID, key: str, value: str | None) -> None:
    if key not in SECRET_KEYS:
        raise ValueError(f"Unknown secret {key}")
    row = (
        await db.execute(select(IntegrationSecret).where(IntegrationSecret.tenant_id == tenant_id, IntegrationSecret.key == key))
    ).scalar_one_or_none()
    if not value:
        if row is not None:
            await db.delete(row)
        return
    if row is None:
        db.add(IntegrationSecret(tenant_id=tenant_id, key=key, value_encrypted=encrypt_secret(value)))
    else:
        row.value_encrypted = encrypt_secret(value)
        row.updated_at = utcnow()


async def secret_flags(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, bool]:
    return {k: bool(await get_secret(db, tenant_id, k)) for k in SECRET_KEYS}


def integration_config(tenant: Tenant) -> dict[str, Any]:
    s = get_settings()
    cfg = (tenant.settings or {}).get("integrations", {}) or {}
    ten = cfg.get("ten_static", {}) or {}
    wp = cfg.get("wordpress", {}) or {}
    wh = cfg.get("webhook", {}) or {}
    li = cfg.get("linkedin", {}) or {}
    brand = (tenant.settings or {}).get("brand", {}) or {}
    return {
        "default_target": ((tenant.settings or {}).get("publishing", {}) or {}).get("default_target") or s.publish_target,
        "ten_static": {
            "site_url": ten.get("site_url") or brand.get("site_url") or s.ten_site_url,
            "public_root": ten.get("public_root") or s.ten_public_root,
            "sftp_host": ten.get("sftp_host") or s.ten_sftp_host,
            "sftp_port": int(ten.get("sftp_port") or s.ten_sftp_port),
            "sftp_user": ten.get("sftp_user") or s.ten_sftp_user,
            "sftp_key_path": ten.get("sftp_key_path") or s.ten_sftp_key_path,
        },
        "wordpress": {"url": wp.get("url") or s.wordpress_url, "user": wp.get("user") or s.wordpress_user},
        "webhook": {"url": wh.get("url") or s.webhook_url},
        "linkedin": {
            "client_id": li.get("client_id") or s.linkedin_client_id,
            "redirect_uri": li.get("redirect_uri") or s.linkedin_redirect_uri or f"{s.app_base_url.rstrip('/')}/api/v1/settings/integrations/linkedin/callback",
            "org_urn": li.get("org_urn") or s.linkedin_org_urn,
            "author_type": li.get("author_type") or ((tenant.settings or {}).get("social", {}) or {}).get("author_type", "organization"),
        },
    }


async def linkedin_state(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    row = (
        await db.execute(select(KVState).where(KVState.tenant_id == tenant_id, KVState.key == "linkedin.token"))
    ).scalar_one_or_none()
    return dict(row.value) if row else {}


async def set_linkedin_state(db: AsyncSession, tenant_id: uuid.UUID, value: dict[str, Any]) -> None:
    row = (
        await db.execute(select(KVState).where(KVState.tenant_id == tenant_id, KVState.key == "linkedin.token"))
    ).scalar_one_or_none()
    if row is None:
        db.add(KVState(tenant_id=tenant_id, key="linkedin.token", value=value))
    else:
        row.value = value
        row.updated_at = utcnow()


async def kv_get(db: AsyncSession, tenant_id: uuid.UUID, key: str) -> dict[str, Any] | None:
    row = (await db.execute(select(KVState).where(KVState.tenant_id == tenant_id, KVState.key == key))).scalar_one_or_none()
    return dict(row.value) if row else None


async def kv_set(db: AsyncSession, tenant_id: uuid.UUID, key: str, value: dict[str, Any]) -> None:
    row = (await db.execute(select(KVState).where(KVState.tenant_id == tenant_id, KVState.key == key))).scalar_one_or_none()
    if row is None:
        db.add(KVState(tenant_id=tenant_id, key=key, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()
