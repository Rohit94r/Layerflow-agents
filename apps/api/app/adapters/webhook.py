"""webhook — POST the article to the tenant's deploy pipeline, HMAC-signed (plan §14.2)."""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx

from app.adapters.base import AdapterError, PublishContext, PublishResult


class WebhookAdapter:
    name = "webhook"

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def validate(self, ctx: PublishContext) -> list[str]:
        issues = []
        if not ctx.config.get("url"):
            issues.append("Webhook URL not configured")
        if not ctx.secrets.get("webhook_secret"):
            issues.append("Webhook secret not configured")
        return issues

    def _body(self, ctx: PublishContext, event: str) -> bytes:
        return json.dumps(
            {
                "event": event,
                "tenant": ctx.tenant_slug,
                "article_id": str(ctx.article_id),
                "category": ctx.category,
                "route": ctx.route,
                "slug": ctx.slug,
                "content_hash": ctx.content_hash,
                "published_at": ctx.published_at.isoformat(),
                "seo": ctx.payload.get("seo"),
                "article": ctx.payload.get("article"),
                "html": ctx.html,
            },
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")

    async def _post(self, ctx: PublishContext, event: str) -> PublishResult:
        issues = await self.validate(ctx)
        if issues:
            raise AdapterError("; ".join(issues))
        body = self._body(ctx, event)
        sig = hmac.new((ctx.secrets.get("webhook_secret") or "").encode(), body, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-LayerFlow-Signature": f"sha256={sig}",
            "X-LayerFlow-Event": event,
            "Idempotency-Key": ctx.content_hash,
        }
        try:
            async with httpx.AsyncClient(timeout=30, transport=self._transport) as client:
                resp = await client.post(ctx.config["url"], content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise AdapterError(f"Webhook unreachable: {exc.__class__.__name__}", retryable=True) from exc
        if resp.status_code >= 500:
            raise AdapterError(f"Webhook error {resp.status_code}", retryable=True)
        if resp.status_code >= 400:
            raise AdapterError(f"Webhook rejected ({resp.status_code}): {resp.text[:300]}")
        try:
            data = resp.json()
        except ValueError:
            data = {}
        url = data.get("url") or (ctx.payload.get("seo") or {}).get("canonical_url") or ""
        return PublishResult(remote_id=str(data.get("id") or ctx.slug), live_url=url)

    async def publish(self, ctx: PublishContext, *, dry_run: bool = False) -> PublishResult:
        if dry_run:
            return PublishResult(remote_id="", live_url="", status="dry_run", warnings=await self.validate(ctx))
        return await self._post(ctx, "article.publish")

    async def update(self, remote_id: str, ctx: PublishContext) -> PublishResult:
        return await self._post(ctx, "article.update")

    async def unpublish(self, remote_id: str, ctx: PublishContext) -> None:
        await self._post(ctx, "article.unpublish")

    async def health(self) -> tuple[bool, str]:
        return True, "configured per tenant"
