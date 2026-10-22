"""wordpress_rest — WP REST API with an application password (plan §14.2)."""

from __future__ import annotations

import re

import httpx

from app.adapters.base import AdapterError, PublishContext, PublishResult


def _body_html(html: str) -> str:
    m = re.search(r'<div itemprop="articleBody">(.*?)</div>\s*(?:<aside|<nav|<section|<div class="blog-tags|<p class="lf-footer)', html, re.S)
    return m.group(1).strip() if m else html


class WordPressAdapter:
    name = "wordpress"

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _auth(self, ctx: PublishContext) -> tuple[str, str, str]:
        url = (ctx.config.get("url") or "").rstrip("/")
        user = ctx.config.get("user") or ""
        pw = ctx.secrets.get("wordpress_app_password") or ""
        if not (url and user and pw):
            raise AdapterError("WordPress URL, user and application password are required")
        return url, user, pw

    async def validate(self, ctx: PublishContext) -> list[str]:
        try:
            self._auth(ctx)
        except AdapterError as exc:
            return [str(exc)]
        return []

    def _post_body(self, ctx: PublishContext) -> dict:
        seo = ctx.payload.get("seo") or {}
        art = ctx.payload.get("article") or {}
        return {
            "title": seo.get("h1") or art.get("title"),
            "content": _body_html(ctx.html),
            "excerpt": seo.get("meta_description") or art.get("dek"),
            "slug": ctx.slug,
            "status": "publish",
        }

    async def _send(self, ctx: PublishContext, path: str) -> PublishResult:
        url, user, pw = self._auth(ctx)
        try:
            async with httpx.AsyncClient(timeout=30, transport=self._transport) as client:
                resp = await client.post(f"{url}/wp-json/wp/v2/{path}", json=self._post_body(ctx), auth=(user, pw))
        except httpx.HTTPError as exc:
            raise AdapterError(f"WordPress unreachable: {exc.__class__.__name__}", retryable=True) from exc
        if resp.status_code >= 500:
            raise AdapterError(f"WordPress error {resp.status_code}", retryable=True)
        if resp.status_code >= 400:
            raise AdapterError(f"WordPress rejected the post ({resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        return PublishResult(remote_id=str(data.get("id")), live_url=data.get("link") or "")

    async def publish(self, ctx: PublishContext, *, dry_run: bool = False) -> PublishResult:
        if dry_run:
            issues = await self.validate(ctx)
            return PublishResult(remote_id="", live_url="", status="dry_run", warnings=issues, preview=self._post_body(ctx))
        return await self._send(ctx, "posts")

    async def update(self, remote_id: str, ctx: PublishContext) -> PublishResult:
        return await self._send(ctx, f"posts/{remote_id}")

    async def unpublish(self, remote_id: str, ctx: PublishContext) -> None:
        url, user, pw = self._auth(ctx)
        async with httpx.AsyncClient(timeout=30, transport=self._transport) as client:
            resp = await client.post(f"{url}/wp-json/wp/v2/posts/{remote_id}", json={"status": "draft"}, auth=(user, pw))
        if resp.status_code >= 400:
            raise AdapterError(f"WordPress unpublish failed ({resp.status_code})")

    async def health(self) -> tuple[bool, str]:
        return True, "configured per tenant"
