"""ten_static — render HTML from the site template and deliver it atomically (plan §14.3).

Modes
- local (no SFTP host configured): writes to SITE_ROOT/<tenant>/ and the API serves it at /site/<tenant>/…
  for staging review. This is the "live on a staging path" proof from Phase 6.
- sftp: uploads to <public_root>/.layerflow-staging/… then renames into place, keeps the previous file in
  .layerflow-history/ for rollback, merges sitemap.xml, verifies the live URL.

The adapter never deletes files it did not create (tracked in .layerflow-manifest.json)."""

from __future__ import annotations

import asyncio
import json
import os
import posixpath
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.adapters.base import AdapterError, PublishContext, PublishResult
from app.core.config import get_settings
from app.services import sitemap
from app.services.render import validate_html

MANIFEST = ".layerflow-manifest.json"


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


class TenStaticAdapter:
    name = "ten_static"

    def __init__(self, fetcher: Any = None) -> None:
        self.fetcher = fetcher

    # ---------- shared ----------
    @staticmethod
    def mode(ctx: PublishContext) -> str:
        return "sftp" if ctx.config.get("sftp_host") else "local"

    @staticmethod
    def rel_path(ctx: PublishContext) -> str:
        return f"{ctx.route.strip('/')}/{ctx.slug}/index.html"

    def live_url(self, ctx: PublishContext) -> str:
        if self.mode(ctx) == "local":
            base = get_settings().app_base_url.rstrip("/")
            return f"{base}/site/{ctx.tenant_slug}/{ctx.route.strip('/')}/{ctx.slug}/"
        return f"{ctx.site_url.rstrip('/')}{ctx.route}/{ctx.slug}"

    def canonical(self, ctx: PublishContext) -> str:
        return f"{ctx.site_url.rstrip('/')}{ctx.route}/{ctx.slug}"

    async def validate(self, ctx: PublishContext) -> list[str]:
        title = (ctx.payload.get("seo") or {}).get("h1") or (ctx.payload.get("article") or {}).get("title")
        issues = validate_html(ctx.html, expected_h1=title)
        if self.mode(ctx) == "sftp" and not (ctx.config.get("sftp_user") and (ctx.config.get("sftp_key_path") or ctx.secrets.get("ten_sftp_password"))):
            issues.append("SFTP host set but user/key missing")
        return issues

    async def publish(self, ctx: PublishContext, *, dry_run: bool = False) -> PublishResult:
        issues = await self.validate(ctx)
        if issues:
            raise AdapterError("Pre-publish validation failed: " + "; ".join(issues))
        if dry_run:
            return PublishResult(
                remote_id=self.rel_path(ctx),
                live_url=self.live_url(ctx),
                status="dry_run",
                artifacts=[self.rel_path(ctx), "sitemap.xml"],
                preview={"mode": self.mode(ctx), "path": self.rel_path(ctx), "canonical": self.canonical(ctx)},
            )
        if self.mode(ctx) == "local":
            return await asyncio.to_thread(self._publish_local, ctx)
        result = await asyncio.to_thread(self._publish_sftp, ctx)
        await self._verify_http(ctx, result)
        return result

    async def update(self, remote_id: str, ctx: PublishContext) -> PublishResult:
        return await self.publish(ctx)

    async def unpublish(self, remote_id: str, ctx: PublishContext) -> None:
        if self.mode(ctx) == "local":
            await asyncio.to_thread(self._rollback_local, ctx)
        else:
            await asyncio.to_thread(self._rollback_sftp, ctx)

    async def health(self) -> tuple[bool, str]:
        return True, "ten_static ready"

    # ---------- local ----------
    def _root(self, ctx: PublishContext) -> Path:
        return Path(get_settings().site_root) / ctx.tenant_slug

    def _manifest(self, root: Path) -> dict[str, Any]:
        p = root / MANIFEST
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                return {}
        return {}

    def _write_atomic(self, path: Path, text: str, staging: Path) -> None:
        staging.mkdir(parents=True, exist_ok=True)
        tmp = staging / f"{uuid.uuid4().hex}.tmp"
        tmp.write_text(text, encoding="utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, path)

    def _publish_local(self, ctx: PublishContext) -> PublishResult:
        root = self._root(ctx)
        staging = root / ".layerflow-staging"
        rel = self.rel_path(ctx)
        target = root / rel
        manifest = self._manifest(root)
        warnings: list[str] = []
        if target.exists():
            if rel not in manifest:
                raise AdapterError(f"{rel} exists and was not created by LayerFlow; refusing to overwrite")
            hist = root / ".layerflow-history" / rel.replace("/index.html", "") / f"{_ts()}.html"
            hist.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, hist)
        self._write_atomic(target, ctx.html, staging)
        entry = manifest.get(rel, {"history": []})
        if entry.get("content_hash") and entry.get("content_hash") != ctx.content_hash:
            entry["history"] = [*entry.get("history", []), {"content_hash": entry["content_hash"], "at": entry.get("published_at")}][-10:]
        entry.update(
            {
                "article_id": str(ctx.article_id),
                "slug": ctx.slug,
                "url": self.canonical(ctx),
                "content_hash": ctx.content_hash,
                "published_at": ctx.published_at.isoformat(),
            }
        )
        manifest[rel] = entry
        self._write_atomic(root / MANIFEST, json.dumps(manifest, indent=2), staging)
        # Sitemap: valid existing entries + live inventory + engine pages; localhost entries dropped.
        sm_path = root / "sitemap.xml"
        existing = sm_path.read_text(encoding="utf-8") if sm_path.exists() else None
        entries: dict[str, datetime | None] = {u: None for u in ctx.inventory_urls}
        for e in manifest.values():
            entries[e["url"]] = datetime.fromisoformat(e["published_at"])
        xml, stats = sitemap.merge(existing, ctx.site_url, entries)
        self._write_atomic(sm_path, xml, staging)
        if stats["dropped_invalid"]:
            warnings.append(f"Sitemap repaired: dropped {stats['dropped_invalid']} invalid (e.g. localhost) entr(ies)")
        # Verify: file present, single H1 with the expected text.
        written = target.read_text(encoding="utf-8")
        title = (ctx.payload.get("seo") or {}).get("h1") or (ctx.payload.get("article") or {}).get("title")
        problems = validate_html(written, expected_h1=title)
        if problems:
            raise AdapterError("Verification failed after write: " + "; ".join(problems))
        return PublishResult(
            remote_id=rel,
            live_url=self.live_url(ctx),
            artifacts=[str(target), str(sm_path)],
            warnings=warnings + [f"Staging site (local mode): sitemap has {stats['urls']} URLs"],
        )

    def _rollback_local(self, ctx: PublishContext) -> None:
        root = self._root(ctx)
        rel = self.rel_path(ctx)
        manifest = self._manifest(root)
        if rel not in manifest:
            raise AdapterError("Nothing to roll back: page was not created by LayerFlow")
        hist_dir = root / ".layerflow-history" / rel.replace("/index.html", "")
        versions = sorted(hist_dir.glob("*.html")) if hist_dir.exists() else []
        target = root / rel
        if versions:
            shutil.copy2(versions[-1], target)
            versions[-1].unlink()
            manifest[rel]["rolled_back_at"] = datetime.now(UTC).isoformat()
        else:
            target.unlink(missing_ok=True)
            manifest.pop(rel, None)
            sm_path = root / "sitemap.xml"
            if sm_path.exists():
                xml, _ = sitemap.merge(sm_path.read_text(encoding="utf-8"), ctx.site_url, {}, remove={self.canonical(ctx)})
                self._write_atomic(sm_path, xml, root / ".layerflow-staging")
        self._write_atomic(root / MANIFEST, json.dumps(manifest, indent=2), root / ".layerflow-staging")

    # ---------- sftp ----------
    def _sftp(self, ctx: PublishContext):
        import paramiko

        cfg = ctx.config
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy() if get_settings().is_production else paramiko.WarningPolicy())
        try:
            client.connect(
                cfg["sftp_host"],
                port=int(cfg.get("sftp_port") or 22),
                username=cfg.get("sftp_user"),
                key_filename=cfg.get("sftp_key_path") or None,
                password=ctx.secrets.get("ten_sftp_password") or None,
                timeout=20,
                allow_agent=False,
                look_for_keys=False,
            )
        except Exception as exc:
            raise AdapterError(f"SFTP connection failed: {exc}", retryable=True) from exc
        return client, client.open_sftp()

    @staticmethod
    def _mkdirs(sftp, path: str) -> None:
        parts = path.strip("/").split("/")
        cur = ""
        for p in parts:
            cur = f"{cur}/{p}"
            try:
                sftp.stat(cur)
            except OSError:
                sftp.mkdir(cur)

    def _put_atomic(self, sftp, root: str, rel: str, data: str) -> None:
        staging = posixpath.join(root, ".layerflow-staging", rel)
        final = posixpath.join(root, rel)
        self._mkdirs(sftp, posixpath.dirname(staging))
        self._mkdirs(sftp, posixpath.dirname(final))
        with sftp.open(staging, "w") as fh:
            fh.write(data.encode("utf-8"))
        try:
            sftp.posix_rename(staging, final)
        except (OSError, AttributeError):
            try:
                sftp.remove(final)
            except OSError:
                pass
            sftp.rename(staging, final)

    def _read(self, sftp, path: str) -> str | None:
        try:
            with sftp.open(path, "r") as fh:
                return fh.read().decode("utf-8", "replace")
        except OSError:
            return None

    def _publish_sftp(self, ctx: PublishContext) -> PublishResult:
        root = ctx.config.get("public_root") or "/public_html"
        rel = self.rel_path(ctx)
        client, sftp = self._sftp(ctx)
        try:
            manifest = json.loads(self._read(sftp, posixpath.join(root, MANIFEST)) or "{}")
            existing = self._read(sftp, posixpath.join(root, rel))
            if existing is not None:
                if rel not in manifest:
                    raise AdapterError(f"{rel} exists on the server and was not created by LayerFlow; refusing to overwrite")
                self._put_atomic(sftp, root, posixpath.join(".layerflow-history", rel.replace("/index.html", ""), f"{_ts()}.html"), existing)
            self._put_atomic(sftp, root, rel, ctx.html)
            manifest[rel] = {
                "article_id": str(ctx.article_id),
                "slug": ctx.slug,
                "url": self.canonical(ctx),
                "content_hash": ctx.content_hash,
                "published_at": ctx.published_at.isoformat(),
            }
            self._put_atomic(sftp, root, MANIFEST, json.dumps(manifest, indent=2))
            sm_existing = self._read(sftp, posixpath.join(root, "sitemap.xml"))
            entries: dict[str, datetime | None] = {u: None for u in ctx.inventory_urls}
            for e in manifest.values():
                entries[e["url"]] = datetime.fromisoformat(e["published_at"])
            xml, stats = sitemap.merge(sm_existing, ctx.site_url, entries)
            self._put_atomic(sftp, root, "sitemap.xml", xml)
        finally:
            sftp.close()
            client.close()
        warnings = [f"Sitemap repaired: dropped {stats['dropped_invalid']} invalid entr(ies)"] if stats["dropped_invalid"] else []
        return PublishResult(remote_id=rel, live_url=self.live_url(ctx), artifacts=[rel, "sitemap.xml"], warnings=warnings)

    def _rollback_sftp(self, ctx: PublishContext) -> None:
        root = ctx.config.get("public_root") or "/public_html"
        rel = self.rel_path(ctx)
        client, sftp = self._sftp(ctx)
        try:
            manifest = json.loads(self._read(sftp, posixpath.join(root, MANIFEST)) or "{}")
            if rel not in manifest:
                raise AdapterError("Nothing to roll back: page was not created by LayerFlow")
            hist_dir = posixpath.join(root, ".layerflow-history", rel.replace("/index.html", ""))
            try:
                versions = sorted(sftp.listdir(hist_dir))
            except OSError:
                versions = []
            if versions:
                prev = self._read(sftp, posixpath.join(hist_dir, versions[-1])) or ""
                self._put_atomic(sftp, root, rel, prev)
                sftp.remove(posixpath.join(hist_dir, versions[-1]))
            else:
                sftp.remove(posixpath.join(root, rel))
                manifest.pop(rel, None)
                self._put_atomic(sftp, root, MANIFEST, json.dumps(manifest, indent=2))
        finally:
            sftp.close()
            client.close()

    async def _verify_http(self, ctx: PublishContext, result: PublishResult) -> None:
        if self.fetcher is None:
            return
        from app.services.fetcher import FetchError

        title = (ctx.payload.get("seo") or {}).get("h1") or (ctx.payload.get("article") or {}).get("title") or ""
        try:
            res = await self.fetcher.get(result.live_url, respect_robots=False, use_cache=False)
        except FetchError as exc:
            if exc.status == 404:
                raise AdapterError(f"Uploaded, but {result.live_url} returns 404 — check the server's routing", retryable=True) from exc
            result.warnings.append(f"Could not verify live URL ({exc}); the CDN may still be caching")
            return
        from markupsafe import escape

        if str(escape(title)) not in res.text and title not in res.text:
            result.warnings.append("Live page responded 200 but the H1 was not found yet (cache?)")
