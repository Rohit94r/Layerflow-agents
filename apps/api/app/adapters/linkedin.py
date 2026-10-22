"""LinkedIn official API (plan §15). OAuth 2.0 + /rest/posts. No browser automation, ever.
Publishing works only when a legitimate token exists; otherwise posts stay `draft_ready` (copy + open flow)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API = "https://api.linkedin.com"
RESERVED = re.compile(r"([\\|{}@\[\]()<>*_~])")


class LinkedInError(Exception):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def to_little_text(text: str) -> str:
    """Escape LinkedIn 'little text format' reserved characters and turn #tags into hashtag entities."""
    out = RESERVED.sub(r"\\\1", text)
    return re.sub(r"(?<![\w\\])#(\w+)", lambda m: "{hashtag|\\#|" + m.group(1) + "}", out)


def authorize_url(client_id: str, redirect_uri: str, state: str, *, organization: bool) -> str:
    scopes = ["openid", "profile", "w_member_social"] + (["w_organization_social"] if organization else [])
    return AUTH_URL + "?" + urlencode(
        {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "state": state, "scope": " ".join(scopes)}
    )


async def _token_request(data: dict[str, str], transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20, transport=transport) as client:
        resp = await client.post(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if resp.status_code >= 400:
        raise LinkedInError(f"Token request failed ({resp.status_code}): {resp.text[:200]}", status=resp.status_code)
    payload = resp.json()
    payload["expires_at"] = (datetime.now(UTC) + timedelta(seconds=int(payload.get("expires_in", 0)))).isoformat()
    if payload.get("refresh_token_expires_in"):
        payload["refresh_expires_at"] = (datetime.now(UTC) + timedelta(seconds=int(payload["refresh_token_expires_in"]))).isoformat()
    return payload


async def exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str, **kw: Any) -> dict[str, Any]:
    return await _token_request(
        {"grant_type": "authorization_code", "code": code, "client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri},
        **kw,
    )


async def refresh(refresh_token: str, client_id: str, client_secret: str, **kw: Any) -> dict[str, Any]:
    return await _token_request(
        {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id, "client_secret": client_secret}, **kw
    )


async def member_urn(token: str, transport: httpx.AsyncBaseTransport | None = None) -> str:
    async with httpx.AsyncClient(timeout=20, transport=transport) as client:
        resp = await client.get(f"{API}/v2/userinfo", headers={"Authorization": f"Bearer {token}"})
    if resp.status_code >= 400:
        raise LinkedInError(f"Could not read LinkedIn profile ({resp.status_code})", status=resp.status_code)
    return f"urn:li:person:{resp.json()['sub']}"


async def create_post(
    token: str,
    author_urn: str,
    text: str,
    *,
    link: str | None = None,
    title: str | None = None,
    description: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    body: dict[str, Any] = {
        "author": author_urn,
        "commentary": to_little_text(text),
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if link:
        body["content"] = {"article": {"source": link, "title": (title or "")[:200], "description": (description or "")[:250]}}
    headers = {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": get_settings().linkedin_api_version,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }
    last: LinkedInError | None = None
    for attempt in range(2):  # retry once on 5xx only, never on 4xx
        try:
            async with httpx.AsyncClient(timeout=30, transport=transport) as client:
                resp = await client.post(f"{API}/rest/posts", json=body, headers=headers)
        except httpx.HTTPError as exc:
            last = LinkedInError(f"LinkedIn unreachable: {exc.__class__.__name__}", retryable=True)
            continue
        if resp.status_code in (200, 201):
            urn = resp.headers.get("x-restli-id") or resp.headers.get("x-linkedin-id") or ""
            if not urn:
                raise LinkedInError("LinkedIn accepted the post but returned no id")
            return urn
        if resp.status_code >= 500 and attempt == 0:
            last = LinkedInError(f"LinkedIn error {resp.status_code}", status=resp.status_code, retryable=True)
            continue
        raise LinkedInError(f"LinkedIn rejected the post ({resp.status_code}): {resp.text[:300]}", status=resp.status_code)
    raise last or LinkedInError("LinkedIn publish failed")
